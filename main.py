import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Form
from pydantic import BaseModel
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt-extractor")

app = FastAPI(
    title="YouTube Video Extractor API",
    version="1.6.0"
)

DEFAULT_PROXY = "http://uiyunatn:tssen2qyz12x@31.59.20.176:6754"
PROXY_URL = os.getenv("PROXY_URL", DEFAULT_PROXY).strip()
COOKIES_FILE_PATH = os.getenv("COOKIES_FILE_PATH", "cookies.txt")
GEO_BYPASS_COUNTRY = os.getenv("GEO_BYPASS_COUNTRY", "US")


def get_base_ytdlp_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocache_dir": True,
        "geo_bypass": True,
        "geo_bypass_country": GEO_BYPASS_COUNTRY,
        "nocheckcertificate": True,
        "prefer_insecure": True,
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


@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "online", "message": "YouTube Extractor Service"}


@app.post("/tasks/youtube")
async def create_youtube_task(
    url: Optional[str] = Form(None),
    link: Optional[str] = Form(None),
    youtube_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None)
):
    """Accepte les formulaires multipart et les champs de type url, link ou youtube_url."""
    target_url = url or link or youtube_url or video_url
    
    if not target_url:
        raise HTTPException(status_code=422, detail="L'URL de la vidéo est manquante (champ url, link ou youtube_url requis).")

    opts = get_base_ytdlp_opts()
    opts["format"] = "best[ext=mp4]/best"
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            return {
                "status": "success",
                "id": info.get("id", ""),
                "title": info.get("title", ""),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "stream_url": info.get("url")
            }
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Erreur d'extraction POST /tasks/youtube : {error_msg}")
        if "407" in error_msg:
            raise HTTPException(
                status_code=407, 
                detail="Erreur Proxy (407). Vérifiez si l'IP Render est autorisée sur le panneau de votre fournisseur de proxy."
            )
        raise HTTPException(status_code=400, detail=f"Erreur d'extraction : {error_msg}")


@app.get("/info", response_model=VideoInfo)
def extract_info(url: str = Query(..., description="URL de la vidéo YouTube")):
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
            raise HTTPException(status_code=407, detail="Proxy Authentication Required.")
        raise HTTPException(status_code=400, detail=f"Erreur d'extraction : {error_msg}")
