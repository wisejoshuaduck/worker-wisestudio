import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt-extractor")

app = FastAPI(
    title="YouTube Video Extractor API",
    version="2.4.0"
)

# Pool de threads pour éviter le blocage synchrone de l'API par yt-dlp
executor = ThreadPoolExecutor(max_workers=3)

PROXY_URL = os.getenv("PROXY_URL", "").strip()
COOKIES_FILE_PATH = "cookies.txt"
GEO_BYPASS_COUNTRY = os.getenv("GEO_BYPASS_COUNTRY", "US")

# Écriture dynamique des cookies depuis la variable d'environnement Render
COOKIES_CONTENT = os.getenv("COOKIES_CONTENT", "").strip()
if COOKIES_CONTENT:
    with open(COOKIES_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(COOKIES_CONTENT)


def get_base_ytdlp_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocache_dir": True,
        "geo_bypass": True,
        "geo_bypass_country": GEO_BYPASS_COUNTRY,
        "nocheckcertificate": True,
        "format": "best/bestvideo+bestaudio",
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb", "android", "ios"],
                "player_skip": ["configs"]
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


@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "online", "message": "YouTube Extractor Service opérationnel."}


@app.post("/tasks/youtube")
async def create_youtube_task(request: Request):
    target_url = None
    
    # 1. Recherche dans les Query Parameters
    target_url = request.query_params.get("url") or request.query_params.get("youtube_url") or request.query_params.get("link")
    
    # 2. Recherche dans le Corps de la requête (JSON, Form-data, URL-encoded)
    if not target_url:
        try:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.json()
                target_url = body.get("url") or body.get("youtube_url") or body.get("link") or body.get("video_url")
            elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                form = await request.form()
                target_url = form.get("url") or form.get("youtube_url") or form.get("link") or form.get("video_url")
        except Exception:
            pass

    if not target_url:
        raise HTTPException(
            status_code=422, 
            detail="L'URL de la vidéo est introuvable. Assurez-vous d'envoyer 'url', 'youtube_url' ou 'link'."
        )

    opts = get_base_ytdlp_opts()

    def extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    try:
        # Exécution non bloquante dans un thread séparé
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(executor, extract)
        
        stream_url = info.get("url")
        if not stream_url and "entries" in info and len(info["entries"]) > 0:
            first_entry = info["entries"][0]
            stream_url = first_entry.get("url") or f"https://www.youtube.com/watch?v={first_entry.get('id')}"

        return {
            "status": "success",
            "id": info.get("id", ""),
            "title": info.get("title", ""),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader"),
            "stream_url": stream_url or info.get("webpage_url")
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Erreur d'extraction POST /tasks/youtube : {error_msg}")
        raise HTTPException(status_code=400, detail=f"Erreur d'extraction : {error_msg}")


@app.get("/info")
async def extract_info(url: str = Query(..., description="URL de la vidéo YouTube")):
    opts = get_base_ytdlp_opts()
    
    def extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(executor, extract)
        return {
            "id": info.get("id", ""),
            "title": info.get("title", ""),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader"),
            "url": info.get("url")
        }
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(status_code=400, detail=f"Erreur d'extraction : {error_msg}")
