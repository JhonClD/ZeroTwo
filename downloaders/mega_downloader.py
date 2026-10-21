"""
mega_downloader.py - Descarga archivos de MEGA con barra de progreso en Telegram y terminal
"""

import re
import logging
import shutil
import subprocess
from pathlib import Path
from downloaders.portable_megatools import ensure_megatools

logger = logging.getLogger(__name__)


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return '▓' * filled + '░' * (width - filled)


class MEGADownloader:
    """Descarga archivos de MEGA con progreso en tiempo real."""

    @staticmethod
    def is_mega_url(url: str) -> bool:
        return bool(re.search(r'mega\.(nz|co\.nz)', url, re.IGNORECASE))

    @staticmethod
    async def download(url: str, output_dir: Path, progress_callback=None) -> tuple[bool, Path | None, str | None]:
        """
        Descarga un archivo de MEGA.
        progress_callback(text) → actualiza el mensaje de Telegram.
        Retorna (success, file_path, error_msg).
        """
        try:
            logger.info("🔷 Iniciando descarga desde MEGA")

            system_megadl = shutil.which('megadl')
            if system_megadl:
                command_prefix = [system_megadl]
                version_command = [system_megadl, '--version']
                tool_label = system_megadl
            else:
                # Hosting sin root: descarga bajo demanda el build estático
                # oficial, lo verifica y lo guarda dentro del proyecto.
                portable_binary = ensure_megatools()
                command_prefix = [str(portable_binary), 'dl']
                version_command = [str(portable_binary), 'dl', '--version']
                tool_label = f"{portable_binary} dl"
                logger.info("Megatools portable verificado y listo para usar")

            if subprocess.run(version_command, capture_output=True, timeout=10).returncode != 0:
                return False, None, "❌ Megatools está presente, pero su comprobación de versión falló."

            if progress_callback:
                await progress_callback(
                    "🔷 <b>Descargando de MEGA</b>\n"
                    "⏳ Iniciando conexión…"
                )

            cmd = [
                *command_prefix,
                '--path', str(output_dir),
                '--print-names',
                url,
            ]

            logger.info(f"🔧 {tool_label} → {output_dir} | URL: {url[:60]}…")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            last_pct    = [-10]
            filename    = None

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                logger.info(f"[MEGA] {line}")

                # megatools muestra líneas como:  45.23% of 234.50 MB, 3.20 MB/s
                m = re.search(r'([\d.]+)%\s+of\s+([\d.]+)\s*(\w+)', line)
                if m:
                    pct      = float(m.group(1))
                    total    = float(m.group(2))
                    unit     = m.group(3)
                    pct_int  = int(pct)

                    # Terminal: siempre
                    logger.info(f"📥 MEGA {pct:.1f}% de {total:.1f} {unit}")

                    # Telegram: cada 10 %
                    if pct_int - last_pct[0] >= 10 and progress_callback:
                        bar = _progress_bar(pct_int)
                        await progress_callback(
                            f"🔷 <b>Descargando de MEGA</b>\n"
                            f"{bar} {pct_int}%\n"
                            f"💾 {total:.1f} {unit} totales"
                        )
                        last_pct[0] = pct_int
                    continue

                # Primera línea que no sea error = nombre del archivo
                if filename is None and not line.upper().startswith('ERROR'):
                    filename = line

            process.wait()

            if process.returncode != 0:
                return False, None, "❌ Megatools terminó con error. Revisa la URL o la conexión del hosting."

            files = sorted(output_dir.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                return False, None, "❌ Archivo no encontrado tras la descarga."

            latest = files[0]
            size_mb = latest.stat().st_size / (1024 * 1024)
            logger.info(f"✅ MEGA descargado: {latest.name} ({size_mb:.1f} MB)")
            return True, latest, None

        except Exception as e:
            logger.error(f"❌ Error MEGA: {e}", exc_info=True)
            return False, None, str(e)
