"""
mediafire_downloader.py - Descarga archivos de MediaFire con barra de progreso en Telegram y terminal
"""

import re
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return '▓' * filled + '░' * (width - filled)


class MediaFireDownloader:
    """Descarga archivos de MediaFire con progreso en tiempo real."""

    @staticmethod
    def is_mediafire_url(url: str) -> bool:
        return bool(re.search(r'mediafire\.com', url, re.IGNORECASE))

    @staticmethod
    async def get_direct_link(url: str) -> tuple[str | None, str | None]:
        """Extrae el enlace directo y nombre del archivo desde la página de MediaFire."""
        try:
            logger.info("🌐 Parseando página de MediaFire…")
            cmd = [
                'curl', '-s', '-L',
                '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return None, None

            html = result.stdout

            # Enlace directo
            direct_url = None
            for pattern in [
                r'<a[^>]*id="downloadButton"[^>]*href="([^"]+)"',
                r'href="(https://download\d+\.mediafire\.com[^"]+)"',
            ]:
                m = re.search(pattern, html)
                if m:
                    direct_url = m.group(1)
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
                m = re.search(pattern, html)
                if m:
                    filename = m.group(1).strip()
                    break

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

        except Exception as e:
            logger.error(f"❌ Error parseando MediaFire: {e}")
            return None, None

    @staticmethod
    async def download(url: str, output_dir: Path, progress_callback=None) -> tuple[bool, Path | None, str | None]:
        """
        Descarga un archivo de MediaFire.
        progress_callback(text) → actualiza el mensaje de Telegram.
        Retorna (success, file_path, error_msg).
        """
        try:
            if progress_callback:
                await progress_callback("🔶 <b>MediaFire</b>\n🔍 Obteniendo enlace de descarga…")

            direct_url, filename = await MediaFireDownloader.get_direct_link(url)
            if not direct_url:
                return False, None, "❌ No se pudo obtener el enlace de descarga de MediaFire."

            output_path = output_dir / filename
            logger.info(f"📥 MediaFire: descargando '{filename}'")
            logger.info(f"   URL: {direct_url[:80]}…")

            if progress_callback:
                await progress_callback(
                    f"🔶 <b>Descargando de MediaFire</b>\n"
                    f"📄 {filename}\n"
                    f"⏳ Iniciando…"
                )

            # Elegir herramienta de descarga
            UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

            def _has(cmd):
                return subprocess.run([cmd, '--version'], capture_output=True).returncode == 0

            if _has('aria2c'):
                cmd = [
                    'aria2c',
                    '-x', '16', '-s', '16', '-k', '1M',
                    '--file-allocation=none',
                    f'--user-agent={UA}',
                    '--allow-overwrite=true',
                    '--auto-file-renaming=false',
                    '--show-console-readout=true',
                    '-d', str(output_dir),
                    '-o', filename,
                    direct_url,
                ]
                tool = 'aria2c'
            elif _has('wget'):
                cmd = [
                    'wget', '-O', str(output_path),
                    '--progress=dot:mega',
                    f'--user-agent={UA}',
                    '--no-check-certificate',
                    '--timeout=30', '--tries=3', '--continue',
                    direct_url,
                ]
                tool = 'wget'
            else:
                cmd = [
                    'curl', '-L', '-C', '-',
                    '-A', UA,
                    '-o', str(output_path),
                    '--progress-bar',
                    direct_url,
                ]
                tool = 'curl'

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
                    m = re.search(r'\((\d+)%\)', line)
                    spd = re.search(r'DL:([\d.]+\w+)', line)
                    if m:
                        pct = int(m.group(1))
                        speed = spd.group(1) if spd else ''
                        logger.info(f"📥 MediaFire {pct}%  {speed}")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            bar = _progress_bar(pct)
                            await progress_callback(
                                f"🔶 <b>Descargando de MediaFire</b>\n"
                                f"📄 {filename}\n"
                                f"{bar} {pct}%\n"
                                f"⚡ {speed}"
                            )
                            last_pct[0] = pct

                # wget: "100%[====] 50.0M  2.50MB/s"
                elif tool == 'wget':
                    m = re.search(r'(\d+)%', line)
                    if m:
                        pct = int(m.group(1))
                        logger.info(f"📥 MediaFire {pct}%")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            bar = _progress_bar(pct)
                            await progress_callback(
                                f"🔶 <b>Descargando de MediaFire</b>\n"
                                f"📄 {filename}\n"
                                f"{bar} {pct}%"
                            )
                            last_pct[0] = pct

                # curl: progreso en formato libre
                else:
                    m = re.search(r'(\d+)\s*%', line)
                    if m:
                        pct = int(m.group(1))
                        logger.info(f"📥 MediaFire {pct}%")
                        if pct - last_pct[0] >= 10 and progress_callback:
                            bar = _progress_bar(pct)
                            await progress_callback(
                                f"🔶 <b>Descargando de MediaFire</b>\n"
                                f"📄 {filename}\n"
                                f"{bar} {pct}%"
                            )
                            last_pct[0] = pct

            process.wait()

            if process.returncode == 0 and output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"✅ MediaFire descargado: {filename} ({size_mb:.1f} MB)")
                return True, output_path, None
            else:
                return False, None, f"❌ {tool} terminó con error (código {process.returncode})"

        except Exception as e:
            logger.error(f"❌ Error MediaFire: {e}", exc_info=True)
            return False, None, str(e)
