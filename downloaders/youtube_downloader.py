"""Descarga de videos públicos de YouTube con yt-dlp."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


class YouTubeDownloadError(RuntimeError):
    """Error legible al resolver o descargar un video de YouTube."""


@dataclass(frozen=True)
class DownloadedYouTubeMedia:
    path: Path
    url: str
    title: str
    channel: str
    thumbnail: str | None


class YouTubeDownloader:
    """Resuelve metadatos y descarga un único video con yt-dlp."""

    @staticmethod
    def _runtime_options() -> dict:
        """Prefiere Deno 2.3+; acepta Node.js 22+ como alternativa."""
        for runtime, executable_name, minimum in (
            ("deno", "deno", (2, 3)),
            ("node", "node", (22, 0)),
        ):
            executable = shutil.which(executable_name)
            if not executable:
                continue
            try:
                result = subprocess.run(
                    [executable, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                version_match = re.search(r"(\d+)\.(\d+)", result.stdout + result.stderr)
                if result.returncode == 0 and version_match:
                    version = (int(version_match.group(1)), int(version_match.group(2)))
                    if version >= minimum:
                        return {"js_runtimes": {runtime: {}}}
            except (OSError, subprocess.TimeoutExpired):
                logger.debug("No se pudo comprobar el runtime %s", runtime, exc_info=True)
        logger.warning(
            "No se detectó Deno 2.3+ ni Node.js 22+; yt-dlp puede no resolver "
            "los desafíos JavaScript actuales de YouTube."
        )
        return {}

    @staticmethod
    def cleanup(output_base: Path) -> None:
        """Elimina archivos finales o parciales creados para esta solicitud."""
        output_base = Path(output_base)
        for path in output_base.parent.glob(f"{output_base.name}.*"):
            if path.is_file():
                path.unlink(missing_ok=True)

    @staticmethod
    def _first_video(info: dict | None) -> dict | None:
        if not info:
            return None
        entries = info.get("entries")
        if entries is not None:
            return next((entry for entry in entries if entry), None)
        return info

    @classmethod
    def download(cls, query: str, output_base: Path, is_video: bool) -> DownloadedYouTubeMedia:
        """Busca o resuelve una URL y descarga un archivo local.

        `output_base` no incluye extensión. Para audio se entrega MP3; para video
        se prefiere MP4 y se limita la resolución a 720p cuando hay formatos compatibles.
        """
        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise YouTubeDownloadError(
                "Falta yt-dlp. Instala las dependencias del proyecto con "
                "`python -m pip install -r requirements.txt`."
            ) from error

        query = query.strip()
        output_base = Path(output_base)
        output_base.parent.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(query)
        if parsed.scheme.lower() in {"http", "https"}:
            if (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
                raise YouTubeDownloadError("El enlace debe pertenecer a YouTube o youtu.be.")
            target = query
        else:
            target = f"ytsearch1:{query}"

        base_options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "cachedir": False,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
        }
        base_options.update(cls._runtime_options())

        try:
            with YoutubeDL({**base_options, "skip_download": True}) as ydl:
                selected = cls._first_video(ydl.extract_info(target, download=False))
            if not selected:
                raise YouTubeDownloadError("No se encontró ningún video para esa búsqueda.")

            video_id = selected.get("id")
            video_url = selected.get("webpage_url") or selected.get("original_url")
            if not video_url and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            if not video_url:
                raise YouTubeDownloadError("yt-dlp no pudo resolver el enlace del video.")

            options = {
                **base_options,
                "outtmpl": f"{output_base}.%(ext)s",
                "overwrites": True,
            }
            if is_video:
                options.update({
                    "format": (
                        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                        "best[height<=720][ext=mp4]/best[height<=720]"
                    ),
                    "merge_output_format": "mp4",
                })
            else:
                options.update({
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                })

            with YoutubeDL(options) as ydl:
                downloaded = ydl.extract_info(video_url, download=True)

            metadata = downloaded or selected
            allowed_extensions = {".mp3"} if not is_video else _VIDEO_EXTENSIONS
            candidates = [
                path for path in output_base.parent.glob(f"{output_base.name}.*")
                if path.is_file()
                and path.suffix.lower() in allowed_extensions
                and path.stat().st_size > 0
            ]
            if not candidates:
                expected = "MP3" if not is_video else "video"
                raise YouTubeDownloadError(f"yt-dlp terminó sin producir un archivo {expected} válido.")

            candidates.sort(
                key=lambda path: (path.suffix.lower() == ".mp4", path.stat().st_size),
                reverse=True,
            )
            return DownloadedYouTubeMedia(
                path=candidates[0],
                url=str(metadata.get("webpage_url") or video_url),
                title=str(metadata.get("title") or selected.get("title") or "Video de YouTube"),
                channel=str(
                    metadata.get("channel")
                    or metadata.get("uploader")
                    or selected.get("channel")
                    or selected.get("uploader")
                    or "YouTube"
                ),
                thumbnail=metadata.get("thumbnail") or selected.get("thumbnail"),
            )
        except YouTubeDownloadError:
            cls.cleanup(output_base)
            raise
        except Exception as error:
            cls.cleanup(output_base)
            message = str(error).strip() or error.__class__.__name__
            if any(token in message.lower() for token in ("javascript", "js runtime", "ejs", "signature")):
                message += " Instala Deno 2.3+ o Node.js 22+ en el hosting para habilitar la resolución JavaScript de YouTube."
            raise YouTubeDownloadError(message) from error
