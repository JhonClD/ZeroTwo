"""
mega_downloader.py - Descarga archivos de MEGA con barra de progreso en Telegram y terminal
"""

import re
import logging
import shutil
import subprocess
from pathlib import Path
from downloaders.portable_megatools import ensure_megatools
from utils.transfer_status import TransferProgress, parse_bytes, render_transfer_status

logger = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(
    r"([\d.]+)%\s+of\s+([\d.]+)\s*([A-Za-z]+)(?:,\s*([\d.]+)\s*([A-Za-z]+/s))?",
    re.IGNORECASE,
)


def parse_megatools_progress(line: str) -> tuple[float, int, int, int | None] | None:
    """Extrae porcentaje, bytes actuales/totales y velocidad de megatools."""
    match = _PROGRESS_RE.search(line or "")
    if not match:
        return None
    percent = min(100.0, max(0.0, float(match.group(1))))
    total = parse_bytes(f"{match.group(2)} {match.group(3)}")
    if not total:
        return None
    current = int(total * percent / 100)
    speed_text = f"{match.group(4)} {match.group(5)}" if match.group(4) and match.group(5) else ""
    speed = parse_bytes(speed_text.removesuffix("/s")) if speed_text else None
    return percent, current, total, speed


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
                    render_transfer_status(
                        "Descargando", "MEGA", "archivo de MEGA", 0, 0, TransferProgress(),
                        context="Conectando…",
                    )
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
            meter = TransferProgress()

            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                logger.info(f"[MEGA] {line}")

                # megatools muestra líneas como:  45.23% of 234.50 MB, 3.20 MB/s
                progress = parse_megatools_progress(line)
                if progress:
                    pct, current_bytes, total_bytes, speed_bytes = progress
                    pct_int  = int(pct)

                    # Terminal: siempre
                    logger.info(f"📥 MEGA {pct:.1f}% — {current_bytes}/{total_bytes} bytes")

                    # Telegram: cada 10 %
                    if pct_int - last_pct[0] >= 10 and progress_callback:
                        await progress_callback(
                            render_transfer_status(
                                "Descargando", "MEGA", Path(filename).name if filename else "archivo de MEGA",
                                current_bytes, total_bytes, meter, speed_override=speed_bytes,
                            )
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
