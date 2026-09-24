"""
VideoProcessor - Clase para procesar videos con FFmpeg
"""

import re
import json
import os
import logging
import subprocess
import inspect
from pathlib import Path

from utils.subtitle_tools import ass_font_style, ass_style

logger = logging.getLogger(__name__)

# Tabla de banderas por código de idioma
_LANG_FLAGS = {
    'SPA': '🇪🇸', 'ESP': '🇪🇸', 'JPN': '🇯🇵', 'JAP': '🇯🇵',
    'ENG': '🇺🇸', 'ENU': '🇺🇸', 'FRA': '🇫🇷', 'FRE': '🇫🇷',
    'GER': '🇩🇪', 'DEU': '🇩🇪', 'POR': '🇧🇷', 'ITA': '🇮🇹',
    'KOR': '🇰🇷', 'CHI': '🇨🇳', 'ZHO': '🇨🇳', 'RUS': '🇷🇺', 'UND': '🏳️',
}


class VideoProcessor:
    """Clase para procesar videos usando FFmpeg"""

    # ─── Utilidades internas ──────────────────────────────────────────────────

    @staticmethod
    def _escape_path(path) -> str:
        """Escapa una ruta para filtros FFmpeg (subtitles=…)."""
        p = str(path).replace('\\', '/').replace(':', '\\:').replace("'", r"\'")
        return f"'{p}'"

    # ─── Análisis de medios ───────────────────────────────────────────────────

    @staticmethod
    def probe_media(input_path):
        """
        Analiza el archivo con FFprobe.
        Retorna {'audio': [...], 'subtitle': [...]} o None si falla.
        """
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams', '-show_format',
                str(input_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            info = {'audio': [], 'subtitle': []}
            sub_count = 0

            for stream in data.get('streams', []):
                s_index = stream.get('index')
                s_type  = stream.get('codec_type')
                tags    = stream.get('tags', {})

                lang_code = tags.get('language', 'UND').upper()
                flag      = _LANG_FLAGS.get(lang_code, '🏳️')
                title     = tags.get('title', 'Pista')
                is_forced = stream.get('disposition', {}).get('forced', 0) == 1
                suffix    = ' (FORZADO)' if is_forced else ''

                if s_type == 'audio':
                    info['audio'].append({
                        'index': s_index,
                        'label': f"{flag} {lang_code} - {title}",
                    })
                elif s_type == 'subtitle':
                    info['subtitle'].append({
                        'index': sub_count,
                        'label': f"{flag} [{sub_count}] {lang_code}{suffix}",
                    })
                    sub_count += 1

            return info

        except Exception as e:
            logger.error(f"❌ Error en probe_media: {e}")
            return None

    # ─── Compresión ───────────────────────────────────────────────────────────

    @staticmethod
    def compress_video_resolution(input_path, output_path, scale=None, bitrate='2000k', crf='23', preset='medium', max_size_mb=None):
        """
        Comprime un video con resolución específica.
        scale: '640:360' para 360p, '1280:720' para 720p, None para original.
        """
        logger.info(f"🎬 Iniciando compresión de video con resolución")
        logger.info(f"📁 Entrada: {input_path}")
        logger.info(f"📁 Salida: {output_path}")
        logger.info(f"📺 Resolución: {scale if scale else 'Original'}")
        logger.info(f"📊 Bitrate: {bitrate}, CRF: {crf}, Preset: {preset}")

        cmd = ['ffmpeg', '-i', input_path]

        if scale:
            if '360' in scale:
                cmd.extend([
                    '-vf', f'scale={scale}:force_original_aspect_ratio=decrease:flags=lanczos,pad={scale}:(ow-iw)/2:(oh-ih)/2',
                    '-c:v', 'libx264', '-crf', crf, '-preset', preset,
                    '-b:v', bitrate, '-maxrate', bitrate, '-bufsize', '900k',
                    '-profile:v', 'main', '-level', '3.1', '-pix_fmt', 'yuv420p',
                ])
            else:
                cmd.extend([
                    '-vf', f'scale={scale}:force_original_aspect_ratio=decrease:flags=lanczos,pad={scale}:(ow-iw)/2:(oh-ih)/2',
                    '-c:v', 'libx264', '-crf', crf, '-preset', preset, '-b:v', bitrate,
                ])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', crf, '-preset', preset, '-b:v', bitrate])

        if '360' in str(scale):
            cmd.extend(['-c:a', 'aac', '-b:a', '96k', '-ar', '44100'])
        else:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])

        cmd.extend(['-movflags', '+faststart', '-y', output_path])

        logger.info(f"🔧 Comando FFmpeg: {' '.join(cmd[:15])}...")

        try:
            logger.info("⏳ Procesando video...")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

            line_count = 0
            for line in process.stderr:
                if 'time=' in line:
                    line_count += 1
                    if line_count % 30 == 0:
                        time_match = re.search(r'time=(\S+)', line)
                        if time_match:
                            logger.info(f"⚙️ Procesando: {time_match.group(1)}")
                elif 'error' in line.lower():
                    logger.error(f"❌ {line.strip()}")

            process.wait()

            if process.returncode != 0:
                logger.error(f"❌ Error en compresión: código {process.returncode}")
                return False

            output_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
            logger.info(f"📦 Tamaño final: {output_size_mb:.2f} MB")
            logger.info("✅ Video comprimido exitosamente")
            return True

        except Exception as e:
            logger.error(f"❌ Error comprimiendo video: {e}")
            return False

    # ─── Thumbnail ────────────────────────────────────────────────────────────

    @staticmethod
    def add_thumbnail_fast(video_path, thumbnail_path, output_path):
        """Añade una portada al video SIN recodificar (ultra rápido)."""
        logger.info(f"🖼️ Iniciando añadido de portada (método rápido)")
        logger.info(f"📁 Video: {video_path}")
        logger.info(f"📁 Imagen: {thumbnail_path}")
        logger.info(f"📁 Salida: {output_path}")

        cmd = [
            'ffmpeg',
            '-i', video_path, '-i', thumbnail_path,
            '-map', '0', '-map', '1', '-c', 'copy',
            '-disposition:v:0', 'default',
            '-disposition:v:1', 'attached_pic',
            '-metadata:s:v:1', 'comment=Cover (front)',
            '-y', output_path,
        ]

        try:
            logger.info("⚡ Añadiendo portada (esto solo toma segundos)...")
            result = subprocess.run(cmd, capture_output=True, stderr=subprocess.PIPE, timeout=60)

            if result.returncode == 0:
                logger.info("✅ Portada añadida exitosamente!")
                return True
            else:
                logger.error(f"❌ Error añadiendo portada: código {result.returncode}")
                logger.error(f"FFmpeg stderr: {result.stderr.decode()[:500]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout añadiendo portada")
            return False
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return False

    # ─── Quemado de subtítulos (mejorado) ─────────────────────────────────────

    @staticmethod
    async def burn_subtitles(
        video_path,
        subtitle_path,
        output_path,
        audio_idx=None,
        sub_idx=None,
        is_external=True,
        external_sub_path=None,
        progress_callback=None,
        crf="23",
        preset="veryfast",
        bitrate=None,
        subtitle_color="white",
        subtitle_alignment="bottom",
        subtitle_size=20,
        subtitle_font="dejavu",
        watermark_color="pink",
        watermark_size=28,
        add_watermark=True,
        cancel_event=None,
        timeout=None,
        process_holder=None,
    ):
        """
        Quema subtítulos en el video con estilo personalizado y marca de agua ZeroTwo.

        Parámetros
        ----------
        video_path        Ruta al video de entrada.
        subtitle_path     Ruta al archivo de subtítulos externo (.srt/.ass/.vtt).
        output_path       Ruta del video de salida.
        audio_idx         Índice de pista de audio (None = primera pista).
        sub_idx           Índice de subtítulo interno (solo si is_external=False).
        is_external       True (defecto) usa subtitle_path / external_sub_path.
        external_sub_path Alias de subtitle_path para compatibilidad con código nuevo.

        Compatibilidad
        --------------
        La firma original burn_subtitles(video_path, subtitle_path, output_path)
        sigue funcionando sin cambios.
        """
        logger.info("📝 Iniciando quemado de subtítulos")
        logger.info(f"📁 Video:      {video_path}")
        logger.info(f"📁 Subtítulos: {subtitle_path or external_sub_path}")
        logger.info(f"📁 Salida:     {output_path}")

        # ── Origen de los subtítulos ──────────────────────────────────────────
        ext_path = external_sub_path or subtitle_path   # compatibilidad

        # libass calcula FontSize según el lienzo del subtítulo. Declarar la
        # resolución original evita que un SRT/ASS se vea enorme o diminuto al
        # renderizar videos 720p, 1080p o archivos con PlayRes diferente.
        original_size = None
        try:
            size_probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', str(video_path)],
                capture_output=True, text=True, timeout=15,
            )
            width_height = size_probe.stdout.strip().split('x')
            if len(width_height) == 2 and all(part.isdigit() for part in width_height):
                original_size = 'x'.join(width_height)
                logger.info("📐 Resolución original para subtítulos: %s", original_size)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("⚠️ No se pudo obtener la resolución original para escalar subtítulos.")

        if is_external and ext_path:
            sub_p = VideoProcessor._escape_path(ext_path)
            sub_filter = f"subtitles={sub_p}"
            logger.info(f"📂 Modo: subtítulos externos → {ext_path}")
        else:
            vid_p = VideoProcessor._escape_path(video_path)
            idx   = sub_idx if sub_idx is not None else 0
            sub_filter = f"subtitles={vid_p}:si={idx}"
            logger.info(f"📂 Modo: subtítulos internos (pista {idx})")
        bundled_fonts = Path(__file__).resolve().parents[1] / "fonts"
        if bundled_fonts.is_dir():
            sub_filter += f":fontsdir={VideoProcessor._escape_path(bundled_fonts)}"
            logger.info("🔤 Fuentes incluidas activadas: %s", bundled_fonts)
        if original_size:
            sub_filter += f":original_size={original_size}"

        # ── Estilo de subtítulos configurable ────────────────────────────────
        sub_style = ass_style(subtitle_color, subtitle_alignment, subtitle_size, font=subtitle_font)
        ass_font_override = ass_font_style(subtitle_font, subtitle_alignment)
        # Los ASS ya contienen color, fuente, tamaño, posición y estilos por diálogo.
        # Para ASS aplicamos únicamente fuente, alineación y margen vertical,
        # conservando colores, tamaños, bordes y demás estilos originales.
        preserve_original_style = (not is_external) or (
            ext_path is not None and Path(ext_path).suffix.lower() == ".ass"
        )
        if preserve_original_style:
            logger.info("🎨 Estilo ASS preservado; fuente=%s, alineación=%s", subtitle_font, subtitle_alignment)

        # ── Marca de agua JhonCID visible (primeros 6 segundos) ───────────────
        watermark = (
            "drawtext=text='JhonCID':"
            "x=30:y=30:"
            "font='DejaVu Sans':"
            f"fontsize={max(20, min(72, int(watermark_size)))}:"
            "fontcolor=0xFF4FA3:"
            "bordercolor=black:"
            "borderw=3:"
            "box=1:"
            "boxcolor=black@0.55:"
            "boxborderw=8:"
            "enable='lt(t,6)'"
        )

        if preserve_original_style:
            styled_sub_filter = f"{sub_filter}:{ass_font_override}" if ass_font_override else sub_filter
        else:
            styled_sub_filter = f"{sub_filter}:{sub_style}"
        full_vf = f"{watermark},{styled_sub_filter}" if add_watermark else styled_sub_filter

        # ── Mapeado de audio ──────────────────────────────────────────────────
        # El signo '?' permite procesar vídeos mudos sin cambiar la política
        # normal: se conserva como máximo la pista de audio seleccionada.
        audio_map = ["-map", f"0:{audio_idx}?"] if audio_idx is not None else ["-map", "0:a:0?"]

        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-map', '0:v:0',
            *audio_map,
            '-vf', full_vf,
            '-c:v', 'libx264',
            '-crf', str(max(16, min(35, int(crf)))),
            '-preset', str(preset),
            '-profile:v', 'main',
            '-level', '3.1',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',
            '-movflags', '+faststart',
            '-threads', '0',
            str(output_path),
        ]
        if bitrate:
            cmd[cmd.index('-crf'):cmd.index('-crf') + 2] = ['-b:v', str(bitrate)]

        logger.info("🔧 Comando FFmpeg construido: %s", " ".join(str(part) for part in cmd))

        try:
            # Total de frames para progreso
            probe_cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=nb_frames',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(video_path),
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            total_frames = 0
            raw = probe_result.stdout.strip()
            if probe_result.returncode == 0 and raw.isdigit():
                total_frames = int(raw)
                logger.info(f"🎬 Total de frames: {total_frames}")

            logger.info("⏳ Quemando subtítulos...")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            if process_holder is not None:
                process_holder["process"] = process

            # ── Leer stderr en thread para no bloquear el event loop ────────
            import asyncio
            import threading

            last_tg_pct = [-10]
            loop = asyncio.get_event_loop()

            def _bar(pct, w=10):
                f = int(w * pct / 100)
                return '\u2593' * f + '\u2591' * (w - f)

            def _read_stderr():
                line_count = 0
                for line in process.stderr:
                    if 'frame=' in line:
                        line_count += 1
                        frame_match = re.search(r'frame=\s*(\d+)', line)
                        fps_match   = re.search(r'fps=\s*([\d.]+)', line)
                        time_match  = re.search(r'time=\s*([\d:.]+)', line)
                        speed_match = re.search(r'speed=\s*([\d.]+)x', line)

                        if frame_match:
                            frame = int(frame_match.group(1))
                            fps   = fps_match.group(1)   if fps_match   else '0'
                            time  = time_match.group(1)  if time_match  else '00:00:00'
                            speed = speed_match.group(1) if speed_match else '0'

                            if total_frames > 0:
                                pct = int((frame / total_frames) * 100)
                                if line_count % 30 == 0:
                                    logger.info(
                                        f"⚙️ Subtítulos {pct}% | "
                                        f"Frame: {frame}/{total_frames} | "
                                        f"FPS: {fps} | Time: {time} | Speed: {speed}x"
                                    )
                                if pct - last_tg_pct[0] >= 10 and progress_callback:
                                    bar = _bar(pct)
                                    text = (
                                        f"📝 <b>Quemando subtítulos</b>\n"
                                        f"{bar} {pct}%\n"
                                        f"🎞 Frame: {frame}/{total_frames} | ⚡ {speed}x"
                                    )
                                    try:
                                        update = progress_callback(text)
                                        if inspect.isawaitable(update):
                                            asyncio.run_coroutine_threadsafe(update, loop)
                                        else:
                                            logger.debug("Callback de progreso completado de forma síncrona; se omite su programación async.")
                                    except Exception:
                                        logger.debug("No se pudo actualizar el progreso de subtítulos", exc_info=True)
                                    last_tg_pct[0] = pct
                            else:
                                if line_count % 30 == 0:
                                    logger.info(f"⚙️ Frame: {frame} | FPS: {fps} | Time: {time}")

                    elif 'error' in line.lower():
                        logger.warning(f"⚠️ FFmpeg: {line.strip()}")

            reader = threading.Thread(target=_read_stderr, daemon=True)
            reader.start()

            started_at = asyncio.get_running_loop().time()
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("🛑 Cancelación solicitada; terminando FFmpeg")
                    process.terminate()
                    try:
                        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
                    except asyncio.TimeoutError:
                        logger.warning("⚠️ FFmpeg no terminó tras SIGTERM; se fuerza su cierre")
                        process.kill()
                        await asyncio.to_thread(process.wait)
                    break
                if timeout is not None and asyncio.get_running_loop().time() - started_at > timeout:
                    logger.warning("⏱️ Tiempo máximo de FFmpeg excedido: %ss", timeout)
                    process.terminate()
                    try:
                        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await asyncio.to_thread(process.wait)
                    break
                await asyncio.sleep(0.25)
            # FFmpeg ya terminó; no permitimos que un lector de stderr defectuoso
            # deje bloqueado el flujo de respuesta de Telegram.
            reader.join(timeout=5)
            if reader.is_alive():
                logger.warning("⚠️ El lector de progreso no cerró a tiempo; se continúa con el archivo generado.")

            cancelled = cancel_event is not None and cancel_event.is_set()
            if process.returncode == 0 and not cancelled and Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                output_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
                logger.info(f"✅ Subtítulos quemados exitosamente")
                logger.info(f"📦 Tamaño final: {output_size_mb:.2f} MB")
                logger.info("🏁 PROCESO COMPLETADO | quemado de subtítulos | salida=%s", output_path)
                return True
            else:
                logger.error(f"❌ Error quemando subtítulos: código {process.returncode}")
                Path(output_path).unlink(missing_ok=True)
                return False

        except Exception as e:
            logger.error(f"❌ Error en burn_subtitles: {e}", exc_info=True)
            Path(output_path).unlink(missing_ok=True)
            return False
        finally:
            if process_holder is not None:
                process_holder["process"] = None

    # ─── Extracción de audio ──────────────────────────────────────────────────


    @staticmethod
    def get_video_meta(video_path, thumb_path):
        """Obtiene duración y genera una miniatura JPEG compatible con Telegram."""
        duration = 0
        video_path = Path(video_path)
        thumb_path = Path(thumb_path)

        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "format=duration:stream=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 str(video_path)],
                capture_output=True, text=True, timeout=15,
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
                logger.warning("⚠️ ffprobe no devolvió una duración válida: %s", probe.stderr.strip()[:300])
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("⚠️ No se pudo obtener duración con ffprobe: %s", error)

        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb = None
        # Buscar un frame cercano al centro; -ss después de -i funciona mejor
        # con videos cuyos índices no permiten seek rápido.
        seek = max(0, duration // 2)
        commands = [
            ["ffmpeg", "-y", "-i", str(video_path), "-ss", str(seek),
             "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3",
             "-f", "image2", str(thumb_path)],
            ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
             "-vf", "scale=640:-2", "-q:v", "3", "-f", "image2",
             str(thumb_path)],
        ]
        for command in commands:
            try:
                result = subprocess.run(command, capture_output=True, timeout=30)
                if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                    thumb = str(thumb_path)
                    break
                logger.warning("⚠️ ffmpeg no generó miniatura: %s", result.stderr.decode(errors="ignore")[-300:])
            except (OSError, subprocess.TimeoutExpired) as error:
                logger.warning("⚠️ Error generando miniatura: %s", error)

        return duration, thumb

    @staticmethod
    def extract_audio(video_path, output_path):
        """Extrae el audio de un video en MP3 a 192 kbps."""
        logger.info(f"🎵 Iniciando extracción de audio")
        logger.info(f"📁 Video: {video_path}")
        logger.info(f"📁 Audio salida: {output_path}")

        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-vn', '-acodec', 'libmp3lame', '-b:a', '192k',
            str(output_path),
        ]

        try:
            logger.info("⏳ Extrayendo audio...")
            result = subprocess.run(cmd, capture_output=True)

            if result.returncode == 0:
                audio_size = Path(output_path).stat().st_size / (1024 * 1024)
                logger.info(f"✅ Audio extraído exitosamente ({audio_size:.2f} MB)")
            else:
                logger.error(f"❌ Error extrayendo audio: código {result.returncode}")
                logger.error(f"FFmpeg stderr: {result.stderr.decode()[:500]}")

            return result.returncode == 0

        except Exception as e:
            logger.error(f"❌ Error extrayendo audio: {e}")
            return False
