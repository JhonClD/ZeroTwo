"""Adaptación directa de Compres-harsub para ZeroTwo.

Comandos disponibles, iguales al plugin original:
    /dw
    /dw2 <resolución> [doc]
    /dw3 <resolución> <audio> <sub> [doc]
    /dw4 [doc]
    /mi <resolución> <pesoMB> [doc]

Todos operan sobre el video al que se responde.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from pyrogram import filters
from pyrogram.types import Message

from utils.video_processing import (
    VideoProcessingError,
    build_compression_command,
    build_hardsub_command,
    build_target_size_commands,
    calculate_video_bitrate,
    probe_video,
    run_ffmpeg,
    safe_video_extension,
)

logger = logging.getLogger(__name__)
MIN_RESOLUTION = 144
MAX_RESOLUTION = 2160


def _resolution(raw: str | None) -> int | None:
    try:
        value = int(raw or "")
    except ValueError:
        return None
    return value if MIN_RESOLUTION <= value <= MAX_RESOLUTION else None


def _index(raw: str | None) -> int | None:
    try:
        value = int(raw or "") - 1
    except ValueError:
        return None
    return value if value >= 0 else None


def _duration(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def _language(stream: dict) -> str:
    tags = stream.get("tags") or {}
    return (tags.get("language") or "und").lower()


def _stream_label(stream: dict, ordinal: int) -> str:
    tags = stream.get("tags") or {}
    title = (tags.get("title") or "").strip()
    language = _language(stream)
    codec = stream.get("codec_name") or "unknown"
    suffix = f" · {title}" if title else ""
    return f"Pista {ordinal + 1}: {codec} ({language}){suffix}"


def _usage(command: str) -> str:
    usages = {
        "dw": "*.dw*",
        "dw2": "*.dw2 [resolución] (doc)*",
        "dw3": "*.dw3 [resolución] [audio] [sub] (doc)*",
        "dw4": "*.dw4 (doc)*",
        "mi": "*.mi [resolución] [pesoMB] (doc)*",
    }
    return f"Uso: {usages[command]}\nResponde al video o documento de video que quieras procesar."


def register(app, user_states: dict, work_dir: Path) -> None:
    """Registra únicamente los cinco comandos del plugin Compres-harsub."""
    del user_states
    root = Path(work_dir) / "video_processing"
    root.mkdir(parents=True, exist_ok=True)
    active_chats: set[int] = set()
    threads = max(1, min(8, int(os.getenv("ZERO_TWO_FFMPEG_THREADS", "2"))))
    timeout = max(60, int(os.getenv("ZERO_TWO_FFMPEG_TIMEOUT", "7200")))

    async def _progress(status: Message, label: str, current: float, total: float) -> None:
        if total <= 0:
            return
        percent = min(100, max(0, current * 100 / total))
        try:
            await status.edit_text(f"⚙️ {label}\nProgreso: {percent:.0f}%")
        except Exception:
            pass

    async def _probe_streaming(client, quoted: Message) -> dict:
        """Obtiene metadatos como Rikka: alimenta ffprobe por stream y corta pronto."""
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-print_format", "json", "-i", "pipe:0",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout = bytearray()
        metadata_ready = asyncio.Event()

        async def collect_output() -> None:
            if process.stdout is None:
                return
            while chunk := await process.stdout.read(8192):
                stdout.extend(chunk)
                if b'"format"' in stdout:
                    metadata_ready.set()

        reader = asyncio.create_task(collect_output())
        try:
            async for chunk in client.stream_media(quoted):
                if metadata_ready.is_set():
                    break
                if process.stdin is None:
                    break
                process.stdin.write(chunk)
                await process.stdin.drain()
            if process.stdin is not None:
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=45)
            await reader
        except Exception:
            if process.returncode is None:
                process.kill()
                await process.wait()
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            raise

        try:
            data = json.loads(stdout)
            streams = data.get("streams", [])
            video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
            if not video_streams:
                raise VideoProcessingError("El archivo no contiene una pista de video.")
            duration = float(data.get("format", {}).get("duration") or video_streams[0].get("duration") or 0)
            subtitle_streams = []
            subtitle_ordinal = 0
            text_codecs = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text", "microdvd"}
            for stream in streams:
                if stream.get("codec_type") == "subtitle":
                    if (stream.get("codec_name") or "").lower() in text_codecs:
                        subtitle_streams.append({"ordinal": subtitle_ordinal, **stream})
                    subtitle_ordinal += 1
            return {
                "duration": duration,
                "video": video_streams[0],
                "audios": [stream for stream in streams if stream.get("codec_type") == "audio"],
                "subtitle_streams": subtitle_streams,
            }
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise VideoProcessingError("FFprobe no devolvió metadatos válidos.") from error

    async def _run(client, message: Message) -> None:
        command = (message.command[0] if message.command else "").lower()
        args = list(message.command[1:] if message.command else [])
        quoted = message.reply_to_message
        if quoted is None:
            await message.reply_text(_usage(command))
            return

        media = quoted.video or quoted.document
        if media is None:
            await message.reply_text("Responde directamente a un video o documento de video.")
            return
        if quoted.document and not str(getattr(media, "mime_type", "")).startswith("video/"):
            suffix = Path(getattr(media, "file_name", "")).suffix.lower()
            if suffix not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}:
                await message.reply_text("El documento citado no parece ser un video.")
                return

        doc = bool(args and args[-1].lower() == "doc")
        if doc:
            args.pop()
        if command == "dw" and args:
            await message.reply_text(_usage(command))
            return
        if command in {"dw2", "dw3", "mi"} and not args:
            await message.reply_text(_usage(command))
            return
        if command == "dw3" and len(args) != 3:
            await message.reply_text(_usage(command))
            return
        if command == "mi" and len(args) != 2:
            await message.reply_text(_usage(command))
            return
        if command in {"dw2", "dw4"} and args:
            await message.reply_text(_usage(command))
            return

        chat_id = message.chat.id
        if command != "dw" and chat_id in active_chats:
            await message.reply_text("⏳ Ya hay un video procesándose en este chat.")
            return
        if command != "dw":
            active_chats.add(chat_id)

        if command == "dw":
            try:
                info = await _probe_streaming(client, quoted)
                video = info["video"]
                text = (
                    "> *Información del video*\n\n"
                    f"> Resolución: `{video.get('width', '?')}x{video.get('height', '?')}`\n"
                    f"> Duración: `{_duration(info['duration'])}`\n\n"
                    "> *Audios disponibles*\n"
                )
                for ordinal, stream in enumerate(info.get("audios", [])):
                    text += f"- {_stream_label(stream, ordinal)}\n"
                if not info.get("audios"):
                    text += "- `Ninguno`\n"
                text += "\n> *Subtítulos disponibles*\n"
                for ordinal, stream in enumerate(info.get("subtitle_streams", [])):
                    text += f"- {_stream_label(stream, ordinal)}\n"
                if not info.get("subtitle_streams"):
                    text += "- `Ninguno`\n"
                text += "\n_*.dw2 [res] (doc)*_\n_*.dw3 [res] [audio] [sub] (doc)*_\n_*.dw4 (doc)*\n_*.mi [res] [pesoMB] (doc)*_"
                await message.reply_text(text)
            except Exception as error:
                logger.exception("Error analizando dw por streaming")
                await message.reply_text(f"❌ No se pudo analizar el video: {error}")
            return

        job_dir = Path(tempfile.mkdtemp(prefix="zerotwo-video-", dir=root))
        input_path = job_dir / f"input{safe_video_extension(getattr(media, 'file_name', ''), getattr(media, 'mime_type', None))}"
        output_path = job_dir / "output.mp4"
        status = None
        try:
            status = await message.reply_text("📥 Descargando video…")
            await quoted.download(file_name=str(input_path))
            if not input_path.exists() or input_path.stat().st_size == 0:
                raise VideoProcessingError("Telegram no entregó un video válido.")
            info = await probe_video(input_path)

            resolution = 360 if command == "dw4" else _resolution(args[0])
            if resolution is None:
                await message.reply_text(f"❌ Resolución válida: {MIN_RESOLUTION}-{MAX_RESOLUTION}.\n{_usage(command)}")
                return

            duration = float(info["duration"])
            if command == "dw2":
                ffmpeg = build_compression_command(
                    input_path.name, output_path.name, crf=24,
                    scale=f"-2:{resolution}", threads=threads,
                )
                label = f"DW2 {resolution}p"
                filename = f"Video_{resolution}p.mp4"
            elif command == "dw4":
                ffmpeg = build_compression_command(
                    input_path.name, output_path.name, crf=26,
                    scale="-2:360", threads=threads,
                )
                label = "DW4 360p"
                filename = "Video_360p_HD.mp4"
            elif command == "dw3":
                audio = _index(args[1])
                subtitle = _index(args[2])
                if audio is None or audio >= len(info.get("audios", [])):
                    raise VideoProcessingError("La pista de audio seleccionada no existe.")
                if subtitle is None or subtitle >= len(info.get("subtitle_streams", [])):
                    raise VideoProcessingError("La pista de subtítulos seleccionada no existe.")
                ffmpeg = build_hardsub_command(
                    input_path.name, output_path.name,
                    embedded_ordinal=info["subtitle_streams"][subtitle]["ordinal"],
                    audio_ordinal=audio, scale=f"-2:{resolution}", threads=threads,
                )
                label = f"DW3 {resolution}p"
                filename = f"Video_{resolution}p.mp4"
            else:
                target_mb = float(args[1].lower().replace("mb", ""))
                bitrate = calculate_video_bitrate(target_mb, duration, audio_bitrate=96_000)
                first, second = build_target_size_commands(
                    input_path.name, output_path.name, bitrate=bitrate,
                    threads=threads, passlog="twopass", scale=f"-2:{resolution}",
                )
                status_text = f"⚙️ MI {resolution}p → {target_mb:g} MB\nPasada 1/2…"
                await status.edit_text(status_text)
                for index, ffmpeg in enumerate((first, second), 1):
                    if index == 2:
                        await status.edit_text(f"⚙️ MI {resolution}p → {target_mb:g} MB\nPasada 2/2…")
                    await run_ffmpeg(
                        ffmpeg, cwd=job_dir, duration=duration,
                        progress_callback=lambda current, total: _progress(status, f"MI {resolution}p · pasada {index}/2", current, total),
                        timeout_seconds=timeout,
                    )
                filename = f"video_{resolution}p_{target_mb:g}mb.mp4"
                label = f"MI {resolution}p"

            if command != "mi":
                await status.edit_text(f"⚙️ Procesando {label}…")
                await run_ffmpeg(
                    ffmpeg, cwd=job_dir, duration=duration,
                    progress_callback=lambda current, total: _progress(status, label, current, total),
                    timeout_seconds=timeout,
                )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise VideoProcessingError("FFmpeg no generó un archivo de salida.")

            size_mb = output_path.stat().st_size / 1024 / 1024
            caption = f"✅ {label} | {size_mb:.1f} MB"
            if doc:
                await message.reply_document(document=str(output_path), file_name=filename, caption=caption)
            else:
                await message.reply_video(video=str(output_path), caption=caption, supports_streaming=True)
            await status.edit_text("✅ Proceso terminado.")
        except (ValueError, VideoProcessingError) as error:
            if status:
                await status.edit_text(f"❌ {error}")
            else:
                await message.reply_text(f"❌ {error}")
        except Exception:
            logger.exception("Error procesando %s", command)
            if status:
                await status.edit_text("❌ Error al procesar el video. Revisa el formato y vuelve a intentarlo.")
            else:
                await message.reply_text("❌ Error al procesar el video.")
        finally:
            active_chats.discard(chat_id)
            for path in job_dir.glob("*"):
                path.unlink(missing_ok=True)
            job_dir.rmdir()

    @app.on_message(filters.command(["dw", "dw2", "dw3", "dw4", "mi"]))
    async def video_processing_command(client, message: Message):
        await _run(client, message)
