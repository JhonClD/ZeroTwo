"""Motor acotado de FFmpeg para compresión y quemado de subtítulos."""

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
TEXT_SUBTITLE_CODECS = {
    "ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text", "microdvd",
}


class VideoProcessingError(RuntimeError):
    """Error de análisis o procesamiento multimedia que puede mostrarse al usuario."""


def safe_video_extension(filename: str, mime_type: str | None = None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return suffix
    if mime_type == "video/x-matroska":
        return ".mkv"
    if mime_type == "video/webm":
        return ".webm"
    return ".mp4"


def compression_profile(profile: str) -> tuple[int, str, str | None]:
    """Devuelve CRF, preset y resolución máxima de un preset cerrado."""
    profiles = {
        "balanced": (23, "veryfast", None),
        "smaller": (28, "veryfast", None),
        "quality": (20, "veryfast", None),
        "720": (23, "veryfast", "1280:720"),
        "480": (25, "veryfast", "854:480"),
    }
    try:
        return profiles[profile]
    except KeyError as error:
        raise ValueError("Perfil de compresión desconocido.") from error


def calculate_video_bitrate(target_size_mb: float, duration_seconds: float, audio_bitrate: int = 128_000) -> int:
    """Calcula un bitrate de video conservador para un objetivo aproximado en MB."""
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
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
    """Obtiene duración y pistas desde FFprobe sin bloquear el event loop."""
    code, stdout, stderr = await _communicate(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=45,
    )
    if code != 0:
        detail = stderr.decode(errors="replace")[-600:]
        raise VideoProcessingError(f"FFprobe no pudo leer el archivo. {detail}")
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
            continue

    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_streams = []
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
            subtitle_streams.append({"ordinal": ordinal, "label": label or f"Pista {ordinal + 1}"})
        ordinal += 1

    return {
        "duration": duration,
        "video": video_streams[0],
        "audios": audio_streams,
        "subtitle_streams": subtitle_streams,
        "subtitles": subtitle_streams,
    }


async def has_subtitles_filter() -> bool:
    """Comprueba que el binario FFmpeg incluye libass/subtitles."""
    code, stdout, stderr = await _communicate(["ffmpeg", "-hide_banner", "-filters"], timeout=20)
    listing = (stdout + stderr).decode(errors="replace")
    return code == 0 and bool(re.search(r"^\s*[.A-Z]{3}\s+subtitles\s", listing, re.MULTILINE))


def _base_command(
    input_name: str,
    output_name: str,
    threads: int,
    *,
    preset: str = "veryfast",
    audio_bitrate: int = 128_000,
    maxrate: int | None = None,
    bufsize: int | None = None,
) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
        "-progress", "pipe:1", "-i", input_name,
        "-map_metadata", "0", "-map_chapters", "0", "-map", "0:v:0", "-map", "0:a?",
        "-threads", str(threads),
        "-c:v", "libx264", "-preset", preset, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", str(audio_bitrate), "-movflags", "+faststart", "-sn", output_name,
    ]
    if maxrate is not None and bufsize is not None:
        insert_at = command.index("-pix_fmt")
        command[insert_at:insert_at] = ["-maxrate", str(maxrate), "-bufsize", str(bufsize)]
    return command


def build_compression_command(
    input_name: str,
    output_name: str,
    *,
    crf: int = 23,
    scale: str | None = None,
    threads: int = 2,
    preset: str = "veryfast",
    audio_bitrate: int = 128_000,
    maxrate: int | None = None,
    bufsize: int | None = None,
) -> list[str]:
    if not 18 <= crf <= 32:
        raise ValueError("El CRF debe estar entre 18 y 32.")
    command = _base_command(
        input_name, output_name, threads, preset=preset,
        audio_bitrate=audio_bitrate, maxrate=maxrate, bufsize=bufsize,
    )
    if scale:
        if not re.fullmatch(r"(?:-2|\d+):\d+", scale):
            raise ValueError("Resolución no permitida.")
        insert_at = command.index("-threads")
        command[insert_at:insert_at] = ["-vf", f"scale={scale}:force_original_aspect_ratio=decrease:force_divisible_by=2"]
    insert_at = command.index("-pix_fmt")
    command[insert_at:insert_at] = ["-crf", str(crf)]
    return command


def _base_target_command(input_name: str, output_name: str, *, bitrate: int, audio_bitrate: int, pass_number: int, passlog: str, threads: int, scale: str | None = None) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
        "-progress", "pipe:1", "-i", input_name,
        "-map_metadata", "0", "-map", "0:v:0", "-c:v", "libx264",
        "-preset", "veryfast", "-b:v", str(bitrate), "-pix_fmt", "yuv420p",
        "-threads", str(threads), "-pass", str(pass_number), "-passlogfile", passlog,
    ]
    if scale is not None:
        if not re.fullmatch(r"(?:-2|\d+):\d+", scale):
            raise ValueError("Resolución no permitida.")
        insert_at = command.index("-threads")
        command[insert_at:insert_at] = ["-vf", f"scale={scale}:force_original_aspect_ratio=decrease:force_divisible_by=2"]
    if pass_number == 1:
        command.extend(["-an", "-sn", "-f", "null", os.devnull])
    else:
        command.extend([
            "-map", "0:a?", "-c:a", "aac", "-b:a", str(audio_bitrate),
            "-movflags", "+faststart", "-sn", output_name,
        ])
    return command


def build_target_size_commands(input_name: str, output_name: str, *, bitrate: int, audio_bitrate: int = 128_000, passlog: str = "twopass", threads: int = 2, scale: str | None = None) -> tuple[list[str], list[str]]:
    if bitrate < 100_000:
        raise ValueError("Bitrate de video demasiado bajo.")
    return (
        _base_target_command(input_name, output_name, bitrate=bitrate, audio_bitrate=audio_bitrate, pass_number=1, passlog=passlog, threads=threads, scale=scale),
        _base_target_command(input_name, output_name, bitrate=bitrate, audio_bitrate=audio_bitrate, pass_number=2, passlog=passlog, threads=threads, scale=scale),
    )


def _escape_filter_filename(filename: str) -> str:
    """Escapa un nombre relativo, generado por el bot, para el filtro libass."""
    return filename.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")


def build_hardsub_command(
    input_name: str,
    output_name: str,
    *,
    subtitle_name: str | None = None,
    embedded_ordinal: int | None = None,
    audio_ordinal: int | None = None,
    scale: str | None = None,
    threads: int = 2,
) -> list[str]:
    if (subtitle_name is None) == (embedded_ordinal is None):
        raise ValueError("Debe indicarse una pista interna o un archivo externo de subtítulos.")
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
        "-progress", "pipe:1", "-i", input_name,
    ]
    if subtitle_name is not None:
        if Path(subtitle_name).name != subtitle_name or Path(subtitle_name).suffix.lower() not in {".srt", ".ass", ".ssa", ".vtt"}:
            raise ValueError("Archivo de subtítulos no válido.")
        filter_arg = f"subtitles=filename='{_escape_filter_filename(subtitle_name)}'"
        if Path(subtitle_name).suffix.lower() in {".srt", ".vtt"}:
            filter_arg += ":force_style='FontSize=22,Outline=2,Shadow=1,MarginV=24'"
    else:
        if embedded_ordinal is None or embedded_ordinal < 0:
            raise ValueError("Pista interna no válida.")
        filter_arg = f"subtitles=filename='{_escape_filter_filename(input_name)}':si={embedded_ordinal}"

    if audio_ordinal is not None and audio_ordinal < 0:
        raise ValueError("Pista de audio no válida.")
    if scale is not None and not re.fullmatch(r"(?:-2|\d+):\d+", scale):
        raise ValueError("Resolución no permitida.")
    video_filter = f"scale={scale}:force_original_aspect_ratio=decrease:force_divisible_by=2,{filter_arg}" if scale else filter_arg
    audio_map = f"0:a:{audio_ordinal}?" if audio_ordinal is not None else "0:a?"
    return command + [
        "-map_metadata", "0", "-map_chapters", "0", "-map", "0:v:0", "-map", audio_map,
        "-vf", video_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-threads", str(threads),
        "-movflags", "+faststart", "-sn", output_name,
    ]


async def run_ffmpeg(
    command: list[str],
    *,
    cwd: Path,
    duration: float,
    progress_callback: _PROGRESS_CALLBACK | None = None,
    timeout_seconds: int = 7200,
    progress_label: str | None = None,
) -> None:
    """Ejecuta FFmpeg de forma asíncrona, leyendo ambos pipes y cancelando limpiamente."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise VideoProcessingError("No se encontró FFmpeg. Instala ffmpeg en el hosting.") from error

    stderr_tail: deque[str] = deque(maxlen=35)
    last_update = 0.0
    progress_values: dict[str, str] = {}

    async def read_progress() -> None:
        nonlocal last_update
        if process.stdout is None:
            return
        while line := await process.stdout.readline():
            text = line.decode(errors="replace").strip()
            key, separator, value = text.partition("=")
            if not separator:
                continue
            progress_values[key] = value
            current_seconds = None
            try:
                if key == "out_time_us":
                    current_seconds = int(value) / 1_000_000
                elif key == "out_time_ms":
                    current_seconds = int(value) / 1_000_000
                elif key == "out_time":
                    hours, minutes, seconds = value.split(":")
                    current_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            except (ValueError, TypeError):
                continue
            if current_seconds is None:
                continue
            now = asyncio.get_running_loop().time()
            if now - last_update < 3:
                continue
            last_update = now
            if progress_label:
                try:
                    frame = int(progress_values.get("frame", "0"))
                except ValueError:
                    frame = 0
                percent = min(100, max(0, current_seconds * 100 / duration)) if duration > 0 else 0
                fps = progress_values.get("fps", "0")
                speed = progress_values.get("speed", "0x")
                timestamp = progress_values.get("out_time", "00:00:00.00")
                print(
                    f"\r[[{progress_label}]] Progreso {percent:05.1f}% | "
                    f"Frame: {frame} | FPS: {fps} | Time: {timestamp} | Speed: {speed}",
                    end="",
                    flush=True,
                )
            try:
                if progress_callback:
                    await progress_callback(min(duration, current_seconds), duration)
            except Exception:
                logger.debug("No se pudo actualizar el progreso del trabajo.", exc_info=True)

    async def read_stderr() -> None:
        if process.stderr is None:
            return
        while line := await process.stderr.readline():
            text = line.decode(errors="replace").strip()
            if text:
                stderr_tail.append(text)
                if "error" in text.lower() or "failed" in text.lower():
                    logger.warning("FFmpeg: %s", text[-500:])

    stdout_task = asyncio.create_task(read_progress())
    stderr_task = asyncio.create_task(read_stderr())
    try:
        return_code = await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        await asyncio.gather(stdout_task, stderr_task)
        if progress_label:
            print()
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
        if "No such filter" in detail or "No such filter: 'subtitles'" in detail:
            raise VideoProcessingError("Este FFmpeg no incluye el filtro subtitles/libass; instala una build de FFmpeg con libass.")
        raise VideoProcessingError(f"FFmpeg terminó con error (código {return_code}).\n{detail}")
