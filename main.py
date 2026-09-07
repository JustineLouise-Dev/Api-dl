import os
import re
import uuid
import shutil
import asyncio
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="yt-dlp API")

DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Batas sederhana biar container tidak kebanjiran proses berat sekaligus
MAX_CONCURRENT_JOBS = 2
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


class InfoRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    # "best" (default), "audio" (mp3), atau format_id spesifik dari /info
    format: str = "best"


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-. ]", "_", name)
    return name[:150]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/info")
async def get_info(req: InfoRequest):
    """Ambil metadata video + daftar format yang tersedia, tanpa download."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        loop = asyncio.get_event_loop()

        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(str(req.url), download=False)

        info = await loop.run_in_executor(None, extract)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=f"Gagal mengambil info: {e}")

    formats = [
        {
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "acodec": f.get("acodec"),
            "vcodec": f.get("vcodec"),
            "note": f.get("format_note"),
        }
        for f in info.get("formats", [])
    ]

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "formats": formats,
    }


@app.post("/download")
async def download(req: DownloadRequest):
    """Download video/audio dan kembalikan filenya."""
    job_id = str(uuid.uuid4())
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    if req.format == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    elif req.format == "best":
        ydl_opts = {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"}
    else:
        ydl_opts = {"format": req.format}

    ydl_opts.update(
        {
            "outtmpl": str(job_dir / "%(title).150s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
    )

    async with _semaphore:
        try:
            loop = asyncio.get_event_loop()

            def run_download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(str(req.url), download=True)
                    return ydl.prepare_filename(info)

            filename = await loop.run_in_executor(None, run_download)

            # Kalau ada postprocessing (mis. jadi mp3), ekstensi filename berubah
            if req.format == "audio":
                base = Path(filename).with_suffix("")
                candidate = base.with_suffix(".mp3")
                if candidate.exists():
                    filename = str(candidate)

        except yt_dlp.utils.DownloadError as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"Download gagal: {e}")
        except Exception as e:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=str(e))

    if not os.path.exists(filename):
        raise HTTPException(status_code=500, detail="File hasil download tidak ditemukan")

    return FileResponse(
        path=filename,
        filename=os.path.basename(filename),
        media_type="application/octet-stream",
        background=None,  # file dibersihkan lewat job terpisah / TTL disk, lihat catatan di README
    )
