"""
mediafire_downloader.py - Descarga archivos de MediaFire con barra de progreso en Telegram y terminal
"""

import asyncio
import re
import logging
import shutil
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from utils.transfer_status import TransferProgress, parse_bytes, render_transfer_status

logger = logging.getLogger(__name__)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


class MediaFireDownloader:
    """Descarga archivos de MediaFire con progreso en tiempo real."""

    @staticmethod
    def _download_with_requests(url: str, output_path: Path, referer: str, progress=None) -> int:
        """Descarga sin binarios externos, útil en contenedores de hosting restringidos."""
        headers = {'User-Agent': UA, 'Referer': referer}
        with requests.get(url, headers=headers, stream=True, timeout=(20, 60), allow_redirects=True) as response:
            if response.status_code == 403:
                raise requests.HTTPError(
                    'MediaFire devolvió HTTP 403 al hosting; el sitio/CDN rechazó la solicitud.',
                    response=response,
                )
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                raise ValueError('MediaFire devolvió una página HTML en vez del archivo.')
            try:
                content_length = max(0, int(response.headers.get('Content-Length') or 0))
            except (TypeError, ValueError):
                content_length = 0

            output_path.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            first_chunk = True
            with output_path.open('wb') as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if first_chunk:
                        first_chunk = False
                        if chunk.lstrip()[:20].lower().startswith((b'<!doctype html', b'<html')):
                            raise ValueError('MediaFire entregó una página HTML, no el archivo solicitado.')
                    output.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, content_length)
            if written == 0:
                raise ValueError('MediaFire devolvió un archivo vacío.')
            return written

    @staticmethod
    def _is_html_file(path: Path) -> bool:
        try:
            with path.open('rb') as source:
                sample = source.read(1024).lstrip().lower()
            return sample.startswith((b'<!doctype html', b'<html'))
        except OSError:
            return True

    @staticmethod
    def is_mediafire_url(url: str) -> bool:
        return bool(re.search(r'mediafire\.com', url, re.IGNORECASE))

    @staticmethod
    async def get_direct_link(url: str) -> tuple[str | None, str | None]:
        """Extrae el enlace directo y nombre del archivo desde la página de MediaFire."""
        try:
            logger.info("🌐 Parseando página de MediaFire…")
            response = await asyncio.to_thread(
                requests.get, url, headers={'User-Agent': UA}, timeout=(15, 30), allow_redirects=True
            )
            if response.status_code == 403:
                raise requests.HTTPError(
                    'MediaFire devolvió HTTP 403 al hosting; el sitio rechazó la solicitud.',
                    response=response,
                )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # El botón de descarga es el selector principal; conservar los
            # enlaces de CDN como alternativa por cambios menores del HTML.
            button = soup.select_one('#downloadButton[href]')
            direct_url = button.get('href').strip() if button else None
            if not direct_url:
                for anchor in soup.select('a[href]'):
                    href = anchor.get('href', '').strip()
                    if re.match(r'https?://download\d+\.mediafire\.com/', href, re.I):
                        direct_url = href
                        break

            if not direct_url:
                logger.error("❌ No se encontró enlace de descarga en MediaFire")
                return None, None

            # Nombre del archivo
            filename = None
            for pattern in [
                r'<div[^>]*class="[^"]*promoDownloadName[^"]*"[^>]*title="([^"]+)"',
                r'<div[^>]*class="[^"]*filename[^"]*"[^>]*>([^<]+)',
                r'/file/[^/]+/([^/]+)/',
            ]:
                m = re.search(pattern, response.text)
                if m:
                    filename = m.group(1).strip()
                    break
            if not filename and button:
                filename = button.get('aria-label') or button.get('title')

            if not filename:
                filename = 'mediafire_file'

            filename = re.sub(r'\s+', ' ', filename).strip()
            filename = re.sub(r'[^\w\s\-\.]', '_', filename)

            # Si el nombre quedó sin extensión reconocible (pasa cuando ninguno
            # de los patrones de arriba matchea bien), la sacamos del propio
            # link de descarga directa, que casi siempre trae el nombre real
            # al final (…/xxxxx/Nombre.mp4). Si tampoco hay ahí, .mp4 por
            # defecto: es lo que sirve TioAnime/LatAnime casi siempre y así
            # Telegram lo reconoce como video (duración + miniatura) en vez
            # de mandarlo como documento genérico.
            if not re.search(r'\.\w{2,4}$', filename):
                m_ext = re.search(r'\.([A-Za-z0-9]{2,4})(?:[?#]|$)', direct_url)
                filename = f"{filename}.{m_ext.group(1)}" if m_ext else f"{filename}.mp4"

            logger.info(f"✅ Enlace y nombre obtenidos: {filename}")
            return direct_url, filename

        except requests.HTTPError:
            raise
        except Exception as e:
            logger.error(f"❌ Error parseando MediaFire: {e}")
            return None, None

    @staticmethod
    async def download(
        url: str,
        output_dir: Path,
        progress_callback=None,
        status_renderer=None,
    ) -> tuple[bool, Path | None, str | None]:
        """
        Descarga un archivo de MediaFire.
        progress_callback(text) → actualiza el mensaje de Telegram.
        status_renderer(stage, filename, current, total, meter, speed) → texto opcional
        para personalizar la tarjeta de progreso.
        Retorna (success, file_path, error_msg).
        """
        try:
            if progress_callback:
                await progress_callback("🔶 <b>MediaFire</b>\n🔍 Obteniendo enlace de descarga…")

            direct_url, filename = await MediaFireDownloader.get_direct_link(url)
            if not direct_url:
                return False, None, "❌ No se pudo obtener el enlace de descarga de MediaFire."

            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename
            logger.info(f"📥 MediaFire: descargando '{filename}'")
            logger.info(f"   URL: {direct_url[:80]}…")

            meter = TransferProgress()
            last_reported = [-10]
            last_unknown_update = [0.0]

            async def report_progress(current, total, speed=None):
                if not progress_callback:
                    return
                current = max(0, int(current or 0))
                total = max(0, int(total or 0))
                pct = min(100, int(current * 100 / total)) if total else None
                if pct is not None:
                    if pct - last_reported[0] < 10 and pct != 100:
                        return
                    last_reported[0] = pct
                else:
                    now = asyncio.get_running_loop().time()
                    if now - last_unknown_update[0] < 2:
                        return
                    last_unknown_update[0] = now
                text = (
                    status_renderer("Descargando", filename, current, total, meter, speed)
                    if status_renderer
                    else render_transfer_status(
                        "Descargando", "MediaFire", filename, current, total, meter,
                        speed_override=speed,
                    )
                )
                await progress_callback(text)

            if progress_callback:
                text = (
                    status_renderer("Descargando", filename, 0, 0, meter)
                    if status_renderer
                    else render_transfer_status("Descargando", "MediaFire", filename, 0, 0, meter)
                )
                await progress_callback(text)

            async def _requests_fallback():
                state = [0, 0]

                def update_progress(current, total):
                    state[:] = [current, total]

                task = asyncio.create_task(asyncio.to_thread(
                    MediaFireDownloader._download_with_requests,
                    direct_url, output_path, url, update_progress,
                ))
                while not task.done():
                    await asyncio.sleep(0.5)
                    await report_progress(*state)
                try:
                    size = await task
                except Exception:
                    output_path.unlink(missing_ok=True)
                    raise
                size_mb = size / (1024 * 1024)
                logger.info(f"✅ MediaFire descargado: {filename} ({size_mb:.1f} MB) con requests")
                if progress_callback:
                    text = (
                        status_renderer("Descarga completada", filename, size, size, meter)
                        if status_renderer
                        else render_transfer_status("Descarga completada", "MediaFire", filename, size, size, meter)
                    )
                    await progress_callback(text)
                return True, output_path, None

            # Priorizar clientes del sistema, pero no exigir herramientas que
            # algunos paneles Python (incluido BotKeep) no permiten instalar.
            aria2c = shutil.which('aria2c')
            wget = shutil.which('wget')
            curl = shutil.which('curl')

            if aria2c:
                cmd = [
                    aria2c,
                    '-x', '16', '-s', '16', '-k', '1M',
                    '--file-allocation=none',
                    f'--user-agent={UA}',
                    f'--referer={url}',
                    '--allow-overwrite=true',
                    '--auto-file-renaming=false',
                    '--show-console-readout=true',
                    '-d', str(output_dir),
                    '-o', filename,
                    direct_url,
                ]
                tool = 'aria2c'
            elif wget:
                cmd = [
                    wget, '-O', str(output_path),
                    '--progress=dot:mega',
                    f'--user-agent={UA}',
                    f'--referer={url}',
                    '--timeout=30', '--tries=3', '--continue',
                    direct_url,
                ]
                tool = 'wget'
            elif curl:
                cmd = [
                    curl, '-L', '-C', '-',
                    '-A', UA,
                    '-e', url,
                    '-o', str(output_path),
                    '--progress-bar',
                    direct_url,
                ]
                tool = 'curl'
            else:
                logger.info('🚀 Usando requests de Python para descargar MediaFire')
                return await _requests_fallback()

            logger.info(f"🚀 Usando {tool} para descargar MediaFire")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            last_pct = [-10]

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                # aria2c: "[#abc123 10MiB/100MiB(10%) CN:16 DL:5MiB]"
                if tool == 'aria2c':
                    m = re.search(
                        r'([\d.]+\s*[KMGT]?i?B)/([\d.]+\s*[KMGT]?i?B)\((\d+)%\)',
                        line, re.IGNORECASE,
                    )
                    spd = re.search(r'DL:([\d.]+\s*[KMGT]?i?B)', line, re.IGNORECASE)
                    if m:
                        current = parse_bytes(m.group(1)) or 0
                        total = parse_bytes(m.group(2)) or 0
                        pct = int(m.group(3))
                        speed = parse_bytes(spd.group(1)) if spd else None
                        logger.info(f"📥 MediaFire {pct}%  {speed}")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            await report_progress(current, total, speed)
                            last_pct[0] = pct

                # wget: "100%[====] 50.0M  2.50MB/s"
                elif tool == 'wget':
                    m = re.search(r'(\d+)%', line)
                    if m:
                        pct = int(m.group(1))
                        current_match = re.search(r'\s([\d,.]+)\s*(B|[KMGT]?B)\s+([\d.]+\s*[KMGT]?B/s)', line, re.IGNORECASE)
                        current = parse_bytes(f"{current_match.group(1).replace(',', '')} {current_match.group(2)}") if current_match else (output_path.stat().st_size if output_path.exists() else 0)
                        total = int(current * 100 / pct) if pct else 0
                        speed = parse_bytes(current_match.group(3).removesuffix('/s')) if current_match else None
                        logger.info(f"📥 MediaFire {pct}%")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            await report_progress(current, total, speed)
                            last_pct[0] = pct

                # curl: progreso en formato libre
                else:
                    m = re.search(r'(\d+)\s*%', line)
                    if m:
                        pct = int(m.group(1))
                        current = output_path.stat().st_size if output_path.exists() else 0
                        total = int(current * 100 / pct) if pct else 0
                        logger.info(f"📥 MediaFire {pct}%")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            await report_progress(current, total)
                            last_pct[0] = pct

            process.wait()

            if (process.returncode == 0 and output_path.exists()
                    and output_path.stat().st_size > 0
                    and not MediaFireDownloader._is_html_file(output_path)):
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"✅ MediaFire descargado: {filename} ({size_mb:.1f} MB)")
                return True, output_path, None
            logger.warning("⚠️ %s no produjo un archivo válido; probando fallback HTTP de Python", tool)
            output_path.unlink(missing_ok=True)
            try:
                return await _requests_fallback()
            except Exception as fallback_error:
                return False, None, (
                    f"❌ {tool} no completó la descarga y el fallback de Python también falló: "
                    f"{fallback_error}"
                )

        except Exception as e:
            logger.error(f"❌ Error MediaFire: {e}", exc_info=True)
            return False, None, str(e)
