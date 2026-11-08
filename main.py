import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import yt_dlp

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt-extractor")

app = FastAPI(
    title="YouTube Video Extractor API",
    description="API de récupération et de streaming direct de flux YouTube via yt-dlp",
    version="1.2.0"
)

# Variable d'environnement avec votre proxy d'authentification par défaut
DEFAULT_PROXY = "http://uiyunatn:tssen2qyz12x@31.59.20.176:6754"
PROXY_URL = os.getenv("PROXY_URL", DEFAULT_PROXY).strip()
COOKIES_FILE_PATH = os.getenv("COOKIES_FILE_PATH", "cookies.txt")
GEO_BYPASS_COUNTRY = os.getenv("GEO_BYPASS_COUNTRY", "US")


def get_base_ytdlp_opts() -> dict:
    """Génère les options de base yt-dlp optimisées pour contourner les blocages réseau et proxy."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocache_dir": True,
        "geo_bypass": True,
        "geo_bypass_country": GEO_BYPASS_COUNTRY,
        "nocheckcertificate": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"],
                "player_skip": ["webpage", "configs"]
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
    }

    if PROXY_URL:
        opts["proxy"] = PROXY_URL

    if os.path.isfile(COOKIES_FILE_PATH):
        opts["cookiefile"] = COOKIES_FILE_PATH

    return opts


class VideoInfo(BaseModel):
    id: str
    title: str
    duration: Optional[int]
    thumbnail: Optional[str]
    uploader: Optional[str]
    url: Optional[str]


@app.get("/")
def read_root():
    return {"status": "online", "message": "YouTube Extractor Service est opérationnel."}


@app.get("/info", response_model=VideoInfo)
def extract_info(url: str = Query(..., description="URL de la vidéo YouTube")):
    """Extrait les métadonnées d'une vidéo YouTube."""
    opts = get_base_ytdlp_opts()
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return VideoInfo(
                id=info.get("id", ""),
                title=info.get("title", ""),
                duration=info.get("duration"),
                thumbnail=info.get("thumbnail"),
                uploader=info.get("uploader"),
                url=info.get("url")
            )
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "407" in error_msg:
            logger.error("Erreur 407 Proxy: L'IP de Render ou les identifiants ont été rejetés par le fournisseur du proxy.")
            raise HTTPException(
                status_code=407, 
                detail="Erreur d'authentification Proxy (407). Vérifiez si l'IP de votre serveur doit être autorisée (IP Whitelist)."
            )
        logger.error(f"Erreur d'extraction yt-dlp : {error_msg}")
        raise HTTPException(status_code=400, detail=f"Erreur lors de l'extraction : {error_msg}")
    except Exception as e:
        logger.error(f"Erreur serveur inattendue : {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.")


@app.get("/stream")
async def stream_video(url: str = Query(..., description="URL de la vidéo YouTube")):
    """Extrait l'URL directe du flux vidéo."""
    opts = get_base_ytdlp_opts()
    opts["format"] = "best[ext=mp4]/best"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get("url")

            if not stream_url:
                raise HTTPException(status_code=404, detail="Impossible de trouver un flux direct valide.")

            return {"stream_url": stream_url, "title": info.get("title")}

    except yt_dlp.utils.DownloadError as e:
        if "407" in str(e):
            raise HTTPException(status_code=407, detail="Échec du proxy (407 Proxy Authentication Required).")
        raise HTTPException(status_code=400, detail=str(e))
