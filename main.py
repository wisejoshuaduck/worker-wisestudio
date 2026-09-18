"""
Worker WiseStudio — FastAPI + yt-dlp.

Deux usages, un seul endpoint /tasks/youtube avec un champ "mode" :
  - mode="audio"  : extrait l'audio (pour la pipeline shorts/podcast de
    WiseStudio), le découpe en tronçons de 10 minutes (même convention que
    le chunking déjà en place côté navigateur dans pipeline.js /
    social-format.js, pour rester sous la limite de 24 Mo par requête
    Whisper/Groq), et envoie tous les tronçons en un seul callback
    multipart vers WiseStudio.
  - mode="mp4"    : télécharge la vidéo complète (vidéo+audio fusionnés en
    MP4), fonctionnalité de téléchargement direct indépendante de la
    génération de shorts, et l'envoie en callback à WiseStudio.

Sécurité :
  - clé partagée comparée en temps constant (hmac.compare_digest), jamais
    par égalité simple, pour éviter le timing attack.
  - la durée de la vidéo est vérifiée AVANT tout téléchargement (appel
    yt-dlp en mode "métadonnées seules") : au-delà de MAX_DURATION_SECONDS,
    la requête est refusée immédiatement (HTTP 422), sans jamais lancer de
    téléchargement ni de tâche de fond — WiseStudio n'a donc jamais à
    débiter de Notes ni créer de projet pour une vidéo hors limite.
"""

import hmac
import os
import shutil
import tempfile
import subprocess
from pathlib import Path

import httpx
import yt_dlp
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

API_SECRET = os.getenv("WORKER_SECRET_KEY", "")
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "3600"))  # 1h
CHUNK_SECONDS = 600  # 10 min — même convention que le chunking navigateur

# Variables pour le contournement des blocages de géolocalisation / datacenter
PROXY_URL = os.getenv("PROXY_URL", "")  # ex: http://user:pass@proxy.com:8080 ou socks5://...
GEO_BYPASS_COUNTRY = os.getenv("GEO_BYPASS_COUNTRY", "US")
COOKIES_FILE_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

app = FastAPI(title="WiseStudio Video Worker")


class YoutubeTaskRequest(BaseModel):
    youtube_url: str
    project_id: int
    callback_url: str
    mode: str = "audio"  # "audio" (pipeline shorts/podcast) ou "mp4" (téléchargement direct)


def check_key(x_worker_key: str | None) -> None:
    if not API_SECRET or not x_worker_key or not hmac.compare_digest(x_worker_key, API_SECRET):
        raise HTTPException(status_code=403, detail="Accès non autorisé")


def get_base_ytdlp_opts() -> dict:
    """Génère les options de base yt-dlp avec proxy, geo_bypass, client mobile et User-Agent custom."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "geo_bypass": True,
        "geo_bypass_country": GEO_BYPASS_COUNTRY,
        # Forcer yt-dlp à utiliser les clients iOS/Android/Mobile Web (beaucoup moins restrictifs)
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "mweb", "android"],
                "player_skip": ["webpage", "configs"]
            }
        },
        # Forcer un User-Agent d'un iPhone récent
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        }
    }
    
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
        
    if os.path.isfile(COOKIES_FILE_PATH):
        opts["cookiefile"] = COOKIES_FILE_PATH

    return opts


def probe_duration(youtube_url: str) -> tuple[float, str]:
    """Récupère durée + titre SANS télécharger (appel léger, synchrone)."""
    opts = get_base_ytdlp_opts()
    opts["skip_download"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return float(info.get("duration") or 0), str(info.get("title") or "Vidéo YouTube")


def notify_error(callback_url: str, project_id: int, message: str) -> None:
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(
                callback_url,
                json={"project_id": project_id, "error": message},
                headers={"X-Worker-Key": API_SECRET},
            )
    except Exception:
        pass  # Le callback est notre seul canal d'erreur


def process_audio(youtube_url: str, project_id: int, callback_url: str, duration: float, title: str) -> None:
    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts = get_base_ytdlp_opts()
        ydl_opts.update({
            "format": "bestaudio/best",
            "outtmpl": os.path.join(temp_dir, "source.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }],
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(youtube_url, download=True)

        source_audio = os.path.join(temp_dir, "source.mp3")
        if not os.path.isfile(source_audio):
            raise RuntimeError("Extraction audio échouée (fichier source introuvable).")

        # Découpage en tronçons de 10 min
        chunk_starts = list(range(0, max(int(duration), 1), CHUNK_SECONDS)) or [0]
        chunk_paths: list[Path] = []
        for i, start in enumerate(chunk_starts):
            chunk_path = Path(temp_dir) / f"chunk_{i}.mp3"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", source_audio,
                    "-ss", str(start), "-t", str(CHUNK_SECONDS),
                    "-c", "copy", str(chunk_path),
                ],
                check=True, capture_output=True,
            )
            if chunk_path.is_file() and chunk_path.stat().st_size > 0:
                chunk_paths.append(chunk_path)

        if not chunk_paths:
            raise RuntimeError("Découpage audio échoué : aucun tronçon produit.")

        files = [
            ("chunks", (f"chunk_{i}.mp3", open(p, "rb"), "audio/mpeg"))
            for i, p in enumerate(chunk_paths)
        ]
        data = {
            "project_id": project_id,
            "duration_seconds": duration,
            "title": title,
            "mode": "audio",
            "chunk_starts": ",".join(str(s) for s in chunk_starts[: len(chunk_paths)]),
        }
        headers = {"X-Worker-Key": API_SECRET}
        with httpx.Client(timeout=180.0) as client:
            client.post(callback_url, data=data, files=files, headers=headers)
        for _, (_, fh, _) in files:
            fh.close()

    except Exception as e:
        notify_error(callback_url, project_id, str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def process_mp4(youtube_url: str, project_id: int, callback_url: str, duration: float, title: str) -> None:
    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts = get_base_ytdlp_opts()
        ydl_opts.update({
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": os.path.join(temp_dir, "video.%(ext)s"),
            "merge_output_format": "mp4",
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(youtube_url, download=True)

        video_path = os.path.join(temp_dir, "video.mp4")
        if not os.path.isfile(video_path):
            candidates = [f for f in os.listdir(temp_dir) if f.endswith(".mp4")]
            if not candidates:
                raise RuntimeError("Téléchargement MP4 échoué (fichier introuvable).")
            video_path = os.path.join(temp_dir, candidates[0])

        with open(video_path, "rb") as f:
            files = {"video": ("video.mp4", f, "video/mp4")}
            data = {
                "project_id": project_id,
                "duration_seconds": duration,
                "title": title,
                "mode": "mp4",
            }
            headers = {"X-Worker-Key": API_SECRET}
            with httpx.Client(timeout=300.0) as client:
                client.post(callback_url, data=data, files=files, headers=headers)

    except Exception as e:
        notify_error(callback_url, project_id, str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/tasks/youtube")
async def handle_youtube(
    task: YoutubeTaskRequest,
    background_tasks: BackgroundTasks,
    x_worker_key: str | None = Header(None),
):
    check_key(x_worker_key)

    if task.mode not in ("audio", "mp4"):
        raise HTTPException(status_code=400, detail="mode invalide (attendu: audio | mp4)")

    try:
        duration, title = probe_duration(task.youtube_url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Impossible de lire les métadonnées : {e}")

    if duration <= 0:
        raise HTTPException(status_code=422, detail="Durée de la vidéo introuvable.")
    if duration > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"Vidéo trop longue ({int(duration // 60)} min). Limite : {MAX_DURATION_SECONDS // 60} min.",
        )

    target = process_audio if task.mode == "audio" else process_mp4
    background_tasks.add_task(target, task.youtube_url, task.project_id, task.callback_url, duration, title)

    return {"status": "queued", "project_id": task.project_id, "duration_seconds": duration, "title": title}


@app.get("/health")
async def health():
    return {"ok": True}
