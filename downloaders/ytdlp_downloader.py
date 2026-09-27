"""Descargador genérico basado en yt-dlp.

Se usa para enlaces de sitios compatibles con yt-dlp que no tienen un
handler específico en ZeroTwo. No invoca una shell y desactiva playlists
para evitar descargas accidentales de colecciones completas.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

logger = logging.getLogger(__name__)


class YtDlpDownloader:
    """Descarga un medio individual desde una URL HTTP(S)."""

    @staticmethod
    def is_http_url(url: str) -> bool:
        parsed = urlparse(url.strip())
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    async def download(
        url: str,
        output_dir: Path,
        progress_callback=None,
    ) -> tuple[bool, Path | None, str | None, dict | None]:
        """Descarga ``url`` y devuelve éxito, archivo, error e información."""
        url = url.strip()
        if not YtDlpDownloader.is_http_url(url):
            return False, None, "La URL debe comenzar con http:// o https://", None

        output_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        last_update = {"value": 0.0}

        def report_progress(data: dict) -> None:
            if data.get("status") != "downloading" or progress_callback is None:
                return
            now = loop.time()
            if now - last_update["value"] < 2:
                return
            last_update["value"] = now
            percent = data.get("_percent_str", "?").strip()
            speed = data.get("_speed_str", "?").strip()
            eta = data.get("_eta_str", "?").strip()
            text = f"📥 <b>Descargando</b>\n{percent} · {speed} · ETA {eta}"
            asyncio.run_coroutine_threadsafe(progress_callback(text), loop)

        def download_sync() -> tuple[Path, dict]:
            options = {
                "noplaylist": True,
                "outtmpl": str(output_dir / "%(title).100s [%(id)s].%(ext)s"),
                "format": "bestvideo*+bestaudio/best",
                "merge_output_format": "mp4",
                "restrictfilenames": True,
                "windowsfilenames": True,
                "retries": 2,
                "fragment_retries": 2,
                "socket_timeout": 30,
                "progress_hooks": [report_progress],
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                prepared = Path(ydl.prepare_filename(info))
                candidates = [prepared]
                # Tras fusionar audio/video, yt-dlp puede cambiar la extensión.
                candidates.extend(sorted(prepared.parent.glob(f"{prepared.stem}.*")))
                candidates = [p for p in candidates if p.is_file()]
                if not candidates:
                    raise FileNotFoundError("yt-dlp no generó ningún archivo")
                return max(candidates, key=lambda p: p.stat().st_mtime), info

        try:
            file_path, info = await asyncio.to_thread(download_sync)
            return True, file_path, None, info
        except yt_dlp.utils.DownloadError as error:
            logger.warning("yt-dlp no pudo descargar %s: %s", url[:120], error)
            return False, None, str(error).strip()[:500], None
        except Exception as error:
            logger.exception("Error inesperado en yt-dlp")
            return False, None, str(error)[:500], None
