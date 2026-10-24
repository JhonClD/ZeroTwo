"""Motor de FFmpeg basado en la plantilla de encodeo del bot del Drive.

Todos los modos usan la misma secuencia: remux de video/audio, primera pasada
H.264 y segunda pasada H.264 con audio AAC. El modo de subtítulos añade la
extracción de la pista y el filtro subtitles, sin marcas de agua ni overlays.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)
_PROGRESS_CALLBACK = Callable[[float, float], Awaitable[None]]
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
TEXT_SUBTITLE_CODECS = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text", "microdvd"}
ALLOWED_PRESETS = {"superfast", "veryfast", "fast", "medium"}


class VideoProcessingError(RuntimeError):
    """Error de análisis o procesamiento multimedia."""


def safe_video_extension(filename: str, mime_type: str | None = None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return suffix
    if mime_type == "video/x-matroska":
        return ".mkv"
    if mime_type == "video/webm":
        return ".webm"
    return ".mp4"


def compression_profile(profile: str) -> tuple[str, str, str | None]:
    """Devuelve bitrate, preset y resolución de la plantilla del Drive."""
    profiles = {
        "balanced": ("3500k", "medium", None),
        "smaller": ("2200k", "medium", None),
        "quality": ("4800k", "medium", None),
        "720": ("3000k", "medium", "1280:720"),
        "480": ("1600k", "medium", "854:480"),
    }
    try:
        return profiles[profile]
    except KeyError as error:
        raise ValueError("Perfil de compresión desconocido.") from error


def calculate_video_bitrate(target_size_mb: float, duration_seconds: float, audio_bitrate: int = 128_000) -> int:
    """Calcula el bitrate de video para un tamaño aproximado."""
    if duration_seconds <= 0:
        raise ValueError("No se pudo determinar la duración del video.")
    if not 40 <= target_size_mb <= 1900:
        raise ValueError("El tamaño objetivo debe estar entre 40 y 1900 MB.")
    total_bitrate = target_size_mb * 1024 * 1024 * 8 * 0.94 / duration_seconds
    video_bitrate = int(total_bitrate - audio_bitrate)
    if video_bitrate < 100_000:
        raise ValueError("El tamaño objetivo es demasiado pequeño para la duración del video.")
    return video_bitrate


async def _communicate(command: list[str], timeout: float = 30) -> tuple[int, bytes, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise VideoProcessingError("FFmpeg/FFprobe no está instalado o no está disponible en PATH.") from error
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise VideoProcessingError("FFprobe tardó demasiado al analizar el video.") from error
    return process.returncode or 0, stdout, stderr


async def probe_video(path: Path) -> dict:
    """Obtiene duración y pistas de video/subtítulos mediante FFprobe."""
    code, stdout, stderr = await _communicate(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        timeout=45,
    )
    if code != 0:
        raise VideoProcessingError(f"FFprobe no pudo leer el archivo. {stderr.decode(errors='replace')[-600:]}")
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise VideoProcessingError("FFprobe devolvió metadatos inválidos para este archivo.") from error

    streams = data.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not video_streams:
        raise VideoProcessingError("El archivo no contiene una pista de video.")
    duration = 0.0
    for raw in (data.get("format", {}).get("duration"), video_streams[0].get("duration")):
        try:
            duration = max(duration, float(raw or 0))
        except (TypeError, ValueError):
            pass

    audio = []
    audio_ordinal = 0
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        language = (tags.get("language") or "und").upper()[:8]
        title = (tags.get("title") or "").strip()[:40]
        codec = (stream.get("codec_name") or "audio").upper()
        channels = stream.get("channels")
        channel_label = f"{channels}ch" if channels else ""
        label = " · ".join(part for part in (language, title or codec, channel_label) if part)
        audio.append({"ordinal": audio_ordinal, "label": label or f"Pista {audio_ordinal + 1}"})
        audio_ordinal += 1

    subtitles = []
    ordinal = 0
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        codec = (stream.get("codec_name") or "").lower()
        if codec in TEXT_SUBTITLE_CODECS:
            tags = stream.get("tags") or {}
            language = (tags.get("language") or "und").upper()[:8]
            title = (tags.get("title") or "").strip()[:40]
            label = " · ".join(part for part in (language, title or codec.upper()) if part)
            subtitles.append({"ordinal": ordinal, "label": label or f"Pista {ordinal + 1}"})
        ordinal += 1
    return {"duration": duration, "video": video_streams[0], "audio": audio, "subtitles": subtitles}


async def has_subtitles_filter() -> bool:
    code, stdout, stderr = await _communicate(["ffmpeg", "-hide_banner", "-filters"], timeout=20)
    listing = (stdout + stderr).decode(errors="replace")
    return code == 0 and bool(re.search(r"^\s*[.A-Z]{3}\s+subtitles\s", listing, re.MULTILINE))


def _validate_preset(preset: str) -> None:
    if preset not in ALLOWED_PRESETS:
        raise ValueError("Preset de FFmpeg no permitido.")


def _validate_bitrate(bitrate: str) -> None:
    if not re.fullmatch(r"\d+(?:b|k|M)?", bitrate):
        raise ValueError("Bitrate de video no válido.")


def _escape_filter_filename(filename: str) -> str:
    return filename.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")


def _scale_filter(scale: str | None) -> str | None:
    if scale is None:
        return None
    if scale not in {"1280:720", "854:480"}:
        raise ValueError("Resolución no permitida.")
    return f"scale={scale}:force_original_aspect_ratio=decrease:force_divisible_by=2"


def _remux_command(input_name: str, media_name: str, audio_ordinal: int | None = None) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning", "-progress", "pipe:1",
        "-i", input_name, "-map", "0:v:0",
    ]
    if audio_ordinal is None:
        command += ["-map", "0:a?"]
    elif audio_ordinal >= 0:
        command += ["-map", f"0:a:{audio_ordinal}"]
    command += ["-c:v", "copy", "-c:a", "copy", media_name]
    return command


def _pass_command(
    media_name: str,
    output_name: str,
    *,
    bitrate: str,
    preset: str,
    threads: int,
    pass_number: int,
    passlog: str,
    video_filter: str | None = None,
) -> list[str]:
    temp_name = f"{Path(output_name).stem}_temp.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning", "-progress", "pipe:1",
        "-i", media_name, "-map", "0:v:0", "-c:v", "libx264", "-vb", bitrate,
        "-preset", preset, "-tune", "animation", "-profile:v", "high10", "-pix_fmt", "yuv420p",
        "-color_primaries", "1", "-color_range", "1", "-color_trc", "1", "-colorspace", "1",
        "-threads", str(threads), "-pass", str(pass_number), "-passlogfile", passlog,
    ]
    if video_filter:
        command += ["-vf", video_filter]
    if pass_number == 1:
        command += ["-map", "0:a?", "-an", "-sn", "-f", "mp4", temp_name]
    else:
        command += [
            "-map", "0:a?", "-c:a", "aac", "-ab", "128k", "-ac", "2", "-ar", "44100",
            "-movflags", "+faststart", "-sn", output_name,
        ]
    return command


def _template_commands(
    input_name: str,
    output_name: str,
    *,
    bitrate: str,
    preset: str = "medium",
    scale: str | None = None,
    subtitle_filter: str | None = None,
    audio_ordinal: int | None = None,
    extra_commands: list[list[str]] | None = None,
    extra_files: list[str] | None = None,
    threads: int = 2,
) -> tuple[list[list[str]], list[str]]:
    _validate_bitrate(bitrate)
    _validate_preset(preset)
    scale_filter = _scale_filter(scale)
    vf_parts = [value for value in (scale_filter, subtitle_filter) if value]
    final_filter = ",".join(vf_parts) if vf_parts else None
    stem = Path(input_name).stem
    media_name = f"{stem}_template.mp4"
    passlog = f"{stem}_template.mp4_2pass.log"
    commands = list(extra_commands or [])
    commands += [
        _remux_command(input_name, media_name, audio_ordinal),
        _pass_command(media_name, output_name, bitrate=bitrate, preset=preset, threads=threads, pass_number=1, passlog=passlog, video_filter=scale_filter),
        _pass_command(media_name, output_name, bitrate=bitrate, preset=preset, threads=threads, pass_number=2, passlog=passlog, video_filter=final_filter),
    ]
    temporary = [media_name, f"{Path(output_name).stem}_temp.mp4", f"{passlog}-0.log", f"{passlog}-0.log.mbtree"] + list(extra_files or [])
    return commands, temporary


def build_compression_commands(
    input_name: str,
    output_name: str,
    *,
    bitrate: str,
    preset: str = "medium",
    scale: str | None = None,
    threads: int = 2,
) -> tuple[list[list[str]], list[str]]:
    """Construye la plantilla completa de compresión en dos pasadas."""
    return _template_commands(input_name, output_name, bitrate=bitrate, preset=preset, scale=scale, threads=threads)


def build_target_size_commands(
    input_name: str,
    output_name: str,
    *,
    bitrate: int,
    passlog: str = "twopass",
    threads: int = 2,
) -> tuple[list[list[str]], list[str]]:
    """Construye la misma plantilla usando el bitrate calculado por tamaño."""
    if bitrate < 100_000:
        raise ValueError("Bitrate de video demasiado bajo.")
    commands = [
        _remux_command(input_name, f"{Path(input_name).stem}_template.mp4"),
        _pass_command(f"{Path(input_name).stem}_template.mp4", output_name, bitrate=f"{bitrate}b", preset="medium", threads=threads, pass_number=1, passlog=passlog),
        _pass_command(f"{Path(input_name).stem}_template.mp4", output_name, bitrate=f"{bitrate}b", preset="medium", threads=threads, pass_number=2, passlog=passlog),
    ]
    return commands, [f"{Path(input_name).stem}_template.mp4", f"{passlog}-0.log", f"{passlog}-0.log.mbtree"]


def build_hardsub_template_commands(
    input_name: str,
    output_name: str,
    *,
    subtitle_name: str | None = None,
    embedded_ordinal: int | None = None,
    audio_ordinal: int | None = None,
    bitrate: str = "4800k",
    preset: str = "medium",
    threads: int = 2,
) -> tuple[list[list[str]], list[str]]:
    """Construye la plantilla completa con extracción y quemado de subtítulos."""
    if (subtitle_name is None) == (embedded_ordinal is None):
        raise ValueError("Debe indicarse una pista interna o un archivo externo de subtítulos.")
    if audio_ordinal is not None and audio_ordinal < -1:
        raise ValueError("Pista de audio no válida.")
    if subtitle_name is not None:
        if Path(subtitle_name).name != subtitle_name or Path(subtitle_name).suffix.lower() not in {".srt", ".ass", ".ssa", ".vtt"}:
            raise ValueError("Archivo de subtítulos no válido.")
        extracted_subtitle = subtitle_name
        extra_commands = []
        extra_files = [subtitle_name]
    else:
        if embedded_ordinal is None or embedded_ordinal < 0:
            raise ValueError("Pista interna no válida.")
        extracted_subtitle = f"{Path(input_name).stem}_subs.ass"
        extra_commands = [[
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning", "-progress", "pipe:1",
            "-i", input_name, "-map", f"0:s:{embedded_ordinal}", extracted_subtitle,
        ]]
        extra_files = [extracted_subtitle]
    subtitle_filter = f"subtitles=filename='{_escape_filter_filename(extracted_subtitle)}'"
    return _template_commands(
        input_name, output_name, bitrate=bitrate, preset=preset, subtitle_filter=subtitle_filter,
        audio_ordinal=audio_ordinal, extra_commands=extra_commands, extra_files=extra_files, threads=threads,
    )


async def run_ffmpeg(
    command: list[str],
    *,
    cwd: Path,
    duration: float,
    progress_callback: _PROGRESS_CALLBACK | None = None,
    timeout_seconds: int = 7200,
) -> None:
    """Ejecuta un comando FFmpeg de forma asíncrona y con cancelación limpia."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise VideoProcessingError("No se encontró FFmpeg. Instala ffmpeg en el hosting.") from error

    stderr_tail: deque[str] = deque(maxlen=35)
    last_update = 0.0

    async def read_progress() -> None:
        nonlocal last_update
        if process.stdout is None:
            return
        while line := await process.stdout.readline():
            text = line.decode(errors="replace").strip()
            if not text.startswith("out_time_"):
                continue
            key, _, value = text.partition("=")
            try:
                current = int(value) / 1_000_000 if key in {"out_time_us", "out_time_ms"} else None
                if current is None and key == "out_time":
                    hours, minutes, seconds = value.split(":")
                    current = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            except (ValueError, TypeError):
                continue
            if current is None or not progress_callback:
                continue
            now = asyncio.get_running_loop().time()
            if now - last_update < 3:
                continue
            last_update = now
            try:
                await progress_callback(min(duration, current), duration)
            except Exception:
                logger.debug("No se pudo actualizar el progreso.", exc_info=True)

    async def read_stderr() -> None:
        if process.stderr is None:
            return
        while line := await process.stderr.readline():
            text = line.decode(errors="replace").strip()
            if text:
                stderr_tail.append(text)

    stdout_task = asyncio.create_task(read_progress())
    stderr_task = asyncio.create_task(read_stderr())
    try:
        return_code = await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        await asyncio.gather(stdout_task, stderr_task)
    except asyncio.TimeoutError as error:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise VideoProcessingError("El procesamiento superó el límite de tiempo configurado.") from error
    except asyncio.CancelledError:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
    if return_code != 0:
        detail = "\n".join(stderr_tail)[-1800:]
        if "No such filter" in detail or "subtitles" in detail and "No such filter" in detail:
            raise VideoProcessingError("Este FFmpeg no incluye el filtro subtitles/libass.")
        raise VideoProcessingError(f"FFmpeg terminó con error (código {return_code}).\n{detail}")
