"""Descarga de videos alojados en YourUpload."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from utils.transfer_status import TransferProgress, render_transfer_status

logger = logging.getLogger(__name__)
UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.avi'}


class YourUploadDownloader:
    """Extrae el enlace de video del reproductor YourUpload y lo descarga."""

    @staticmethod
    def is_yourupload_url(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or '').lower().rstrip('.')
        except (TypeError, ValueError):
            return False
        return host == 'yourupload.com' or host.endswith('.yourupload.com')

    @staticmethod
    def _extract_direct_url(page_url: str, page_html: str) -> str | None:
        """Extrae MP4 de los formatos del reproductor usados por YourUpload."""
        source = html.unescape(str(page_html or ''))
        source = (source.replace(r'\u0026', '&')
                        .replace(r'\x26', '&')
                        .replace(r'\/', '/'))
        patterns = [
            r'''file["']?\s*:\s*["'](https?://[^"']+\.mp4[^"']*)["']''',
            r'''sources?\s*:\s*\[\s*\{[^}]*src\s*:\s*["'](https?://[^"']+)["']''',
            r'''video\[[^\]]+\]\s*=\s*["'](https?://[^"']+\.mp4[^"']*)["']''',
            r'''(?:src|data-src|data-file)\s*=\s*["'](https?://[^"']+\.mp4(?:\?[^"']*)?)["']''',
            r'''(https?://[^"'\s<>]+\.mp4(?:\?[^"'\s<>]*)?)''',
        ]
        for index, pattern in enumerate(patterns):
            match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            candidate = match.group(1).replace('&amp;', '&').strip()
            candidate = urljoin(page_url, candidate)
            parsed = urlparse(candidate)
            extension = Path(unquote(parsed.path)).suffix.lower()
            # Rikka también acepta el URL del objeto `sources` aunque el CDN
            # no publique extensión (algunos enlaces son URLs firmadas).
            if parsed.scheme in {'http', 'https'} and (extension in VIDEO_EXTENSIONS or index == 1):
                return candidate
        return None

    @classmethod
    def _get_direct_url_sync(cls, page_url: str) -> str:
        if not cls.is_yourupload_url(page_url):
            raise ValueError('El enlace no pertenece a YourUpload.')
        response = requests.get(
            page_url,
            headers={'User-Agent': UA, 'Referer': page_url},
            timeout=(15, 30),
            allow_redirects=True,
        )
        response.raise_for_status()
        direct_url = cls._extract_direct_url(response.url or page_url, response.text)
        if not direct_url:
            raise ValueError('YourUpload: no se encontró un enlace directo de video en la página.')
        return direct_url

    @staticmethod
    def _download_sync(direct_url: str, output_path: Path, referer: str, progress=None) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with requests.get(
                direct_url,
                headers={'User-Agent': UA, 'Referer': referer},
                stream=True,
                timeout=(20, 90),
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if 'text/html' in content_type or 'application/json' in content_type:
                    raise ValueError('YourUpload devolvió una página web, no el archivo de video.')
                try:
                    total = max(0, int(response.headers.get('Content-Length') or 0))
                except (TypeError, ValueError):
                    total = 0
                with output_path.open('wb') as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        if written == 0 and chunk.lstrip()[:32].lower().startswith((b'<!doctype html', b'<html')):
                            raise ValueError('YourUpload devolvió HTML en vez del archivo de video.')
                        output.write(chunk)
                        written += len(chunk)
                        if progress:
                            try:
                                progress(written, total)
                            except Exception:
                                logger.debug('No se pudo emitir el progreso de YourUpload', exc_info=True)
            if written == 0:
                raise ValueError('YourUpload devolvió un archivo vacío.')
            return written
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    @classmethod
    async def download(
        cls,
        url: str,
        output_dir: Path,
        file_name: str | None = None,
        progress_callback=None,
        status_renderer=None,
    ) -> tuple[bool, Path | None, str | None]:
        """Descarga YourUpload y retorna ``(éxito, ruta, error)``."""
        try:
            direct_url = await asyncio.to_thread(cls._get_direct_url_sync, url)
            parsed = urlparse(direct_url)
            inferred_name = Path(unquote(parsed.path)).name or 'yourupload_video.mp4'
            name = file_name or inferred_name
            if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
                name = f'{name}.mp4'
            output_path = Path(output_dir) / name
            if progress_callback:
                loop = asyncio.get_running_loop()
                meter = TransferProgress()
                last_report = [0.0]

                async def report_progress(current, total):
                    now = loop.time()
                    try:
                        percent = current * 100 / total if total else None
                    except (TypeError, ValueError):
                        percent = None
                    if percent is not None and percent >= 100:
                        pass
                    elif now - last_report[0] < 2.5:
                        return
                    last_report[0] = now
                    text = (
                        status_renderer('Descargando', name, current, total, meter)
                        if status_renderer
                        else render_transfer_status('Descargando', 'YourUpload', name, current, total, meter)
                    )
                    await progress_callback(text)

                async def initial_progress():
                    text = (
                        status_renderer('Descargando', name, 0, 0, meter)
                        if status_renderer
                        else render_transfer_status('Descargando', 'YourUpload', name, 0, 0, meter)
                    )
                    await progress_callback(text)

                await initial_progress()

                def sync_progress(current, total):
                    future = asyncio.run_coroutine_threadsafe(report_progress(current, total), loop)
                    try:
                        future.result(timeout=15)
                    except Exception as progress_error:
                        logger.debug('No se pudo publicar progreso de YourUpload: %s', progress_error)

                size = await asyncio.to_thread(
                    cls._download_sync, direct_url, output_path, url, sync_progress
                )
                await report_progress(size, size)
            else:
                size = await asyncio.to_thread(cls._download_sync, direct_url, output_path, url)
            logger.info('YourUpload descargado: %s (%.1f MB)', output_path.name, size / (1024 * 1024))
            return True, output_path, None
        except Exception as exc:
            logger.warning('Error descargando YourUpload: %s', exc)
            return False, None, str(exc)
