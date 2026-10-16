"""Utilidades de metadatos y miniaturas para videos descargados."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Herramientas multimedia ligeras usadas por los previews de video."""

    @staticmethod
    def get_video_meta(video_path, thumb_path):
        """Obtiene duración con ffprobe y genera una miniatura JPEG para Telegram."""
        duration = 0
        video_path = Path(video_path)
        thumb_path = Path(thumb_path)

        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration:stream=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            values = []
            for line in probe.stdout.splitlines():
                try:
                    value = float(line.strip())
                    if value > 0:
                        values.append(value)
                except ValueError:
                    continue
            if values:
                duration = max(1, round(max(values)))
            else:
                logger.warning(
                    "⚠️ ffprobe no devolvió una duración válida: %s",
                    probe.stderr.strip()[:300],
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("⚠️ No se pudo obtener duración con ffprobe: %s", error)

        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb = None
        seek = max(0, duration // 2)
        commands = [
            [
                "ffmpeg", "-y", "-i", str(video_path), "-ss", str(seek),
                "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3",
                "-f", "image2", str(thumb_path),
            ],
            [
                "ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
                "-vf", "scale=640:-2", "-q:v", "3", "-f", "image2",
                str(thumb_path),
            ],
        ]
        for command in commands:
            try:
                result = subprocess.run(command, capture_output=True, timeout=30)
                if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                    thumb = str(thumb_path)
                    break
                logger.warning(
                    "⚠️ ffmpeg no generó miniatura: %s",
                    result.stderr.decode(errors="ignore")[-300:],
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                logger.warning("⚠️ Error generando miniatura: %s", error)

        return duration, thumb
