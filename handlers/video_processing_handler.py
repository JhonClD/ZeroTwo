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
import html
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from pyrogram import enums, filters
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
LANGUAGE_FLAGS = {
    "spa": "🇲🇽", "es": "🇲🇽", "lat": "🌎", "es-419": "🌎",
    "eng": "🇺🇸", "en": "🇺🇸", "jpn": "🇯🇵", "ja": "🇯🇵",
    "por": "🇧🇷", "pt": "🇧🇷", "ara": "🇸🇦", "ar": "🇸🇦",
    "fre": "🇫🇷", "fra": "🇫🇷", "fr": "🇫🇷", "ger": "🇩🇪",
    "deu": "🇩🇪", "de": "🇩🇪", "ita": "🇮🇹", "it": "🇮🇹",
    "rus": "🇷🇺", "ru": "🇷🇺", "chi": "🇨🇳", "zho": "🇨🇳",
    "cmn": "🇨🇳", "zh": "🇨🇳", "kor": "🇰🇷", "ko": "🇰🇷",
    "dut": "🇳🇱", "nld": "🇳🇱", "nl": "🇳🇱", "pol": "🇵🇱",
    "pl": "🇵🇱", "tur": "🇹🇷", "tr": "🇹🇷", "cze": "🇨🇿",
    "ces": "🇨🇿", "cs": "🇨🇿", "hun": "🇭🇺", "hu": "🇭🇺",
    "rum": "🇷🇴", "ron": "🇷🇴", "ro": "🇷🇴", "swe": "🇸🇪",
    "sv": "🇸🇪", "nor": "🇳🇴", "nob": "🇳🇴", "nb": "🇳🇴",
    "no": "🇳🇴", "dan": "🇩🇰", "da": "🇩🇰", "fin": "🇫🇮",
    "fi": "🇫🇮", "gre": "🇬🇷", "ell": "🇬🇷", "el": "🇬🇷",
    "tha": "🇹🇭", "th": "🇹🇭", "vie": "🇻🇳", "vi": "🇻🇳",
    "ind": "🇮🇩", "id": "🇮🇩", "may": "🇲🇾", "msa": "🇲🇾",
    "ms": "🇲🇾", "hin": "🇮🇳", "hi": "🇮🇳", "ukr": "🇺🇦",
    "uk": "🇺🇦", "heb": "🇮🇱", "he": "🇮🇱", "bul": "🇧🇬",
    "bg": "🇧🇬", "srp": "🇷🇸", "sr": "🇷🇸", "hrv": "🇭🇷",
    "hr": "🇭🇷", "slk": "🇸🇰", "sk": "🇸🇰", "slv": "🇸🇮",
    "sl": "🇸🇮", "und": "🏳️",
}


def _resolution(raw: str | None) -> int | None:
    match = re.match(r"^\s*(\d+)", raw or "")
    if not match:
        return None
    value = int(match.group(1))
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
    flag = LANGUAGE_FLAGS.get(language)
    language_text = f"{flag} ({language})" if flag else f"({language})"
    return f"Pista {ordinal + 1}: {codec} {language_text}{suffix}"


def _stream_html(stream: dict, ordinal: int) -> str:
    tags = stream.get("tags") or {}
    title = html.escape((tags.get("title") or "").strip())
    language = html.escape(_language(stream))
    codec = html.escape(stream.get("codec_name") or "unknown")
    flag = LANGUAGE_FLAGS.get(_language(stream), "")
    title_suffix = f" · {title}" if title else ""
    return f"• Pista {ordinal + 1}: {codec} {flag} ({language}){title_suffix}"


def _dw_html(info: dict) -> str:
    video = info["video"]
    resolution = f"{video.get('width', '?')}x{video.get('height', '?')}"
    audios = info.get("audios", [])
    subtitles = info.get("subtitle_streams", [])
    audio_lines = "\n".join(_stream_html(stream, i) for i, stream in enumerate(audios)) or "• `Ninguno`"
    subtitle_lines = "\n".join(_stream_html(stream, i) for i, stream in enumerate(subtitles)) or "• `Ninguno`"
    return (
        "<blockquote><b>Información del video</b>\n\n"
        f"Resolución: {html.escape(resolution)}\n"
        f"Duración: {_duration(info['duration'])}</blockquote>\n\n"
        "<blockquote><b>Audios disponibles</b>\n\n"
        f"{audio_lines}</blockquote>\n\n"
        "<blockquote><b>Subtítulos disponibles</b>\n\n"
        f"{subtitle_lines}</blockquote>\n\n"
        "<i><b>/dw2 [res] (doc)</b></i>\n"
        "<i><b>/dw3 [res] [audio] [sub] (doc)</b></i>\n"
        "<i><b>/dw4 (doc)</b></i>\n"
        "<i><b>/mi [res] [pesoMB] (doc)</b></i>"
    )


def _usage(command: str) -> str:
    usages = {
        "dw": "<i><b>/dw</b></i>",
        "dw2": "<i><b>/dw2 [resolución] [doc]</b></i>",
        "dw3": "<i><b>/dw3 [resolución] [audio] [sub] [doc]</b></i>",
        "dw4": "<i><b>/dw4 [doc]</b></i>",
        "mi": "<i><b>/mi [resolución] [pesoMB] [doc]</b></i>",
    }
    return f"<b>Uso:</b> {usages[command]}\n<i>Responde al video o documento de video que quieras procesar.</i>"


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
            await status.edit_text(f"⚙️ <b>{html.escape(label)}</b>\nProgreso: {percent:.0f}%", parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    async def _probe_streaming(client, quoted: Message) -> dict:
        """Obtiene metadatos como Rikka: alimenta ffprobe por stream y corta pronto."""
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-probesize", "100K", "-analyzeduration", "100K",
            "-show_streams", "-show_format",
            "-print_format", "json", "-i", "pipe:0",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout = bytearray()
        stderr = bytearray()
        metadata_ready = asyncio.Event()

        async def collect_output() -> None:
            if process.stdout is None:
                return
            while chunk := await process.stdout.read(8192):
                stdout.extend(chunk)
                if b'"format"' in stdout:
                    metadata_ready.set()

        async def collect_errors() -> None:
            if process.stderr is None:
                return
            while chunk := await process.stderr.read(8192):
                stderr.extend(chunk)

        reader = asyncio.create_task(collect_output())
        error_reader = asyncio.create_task(collect_errors())
        stream = client.stream_media(quoted)
        try:
            async for chunk in stream:
                if metadata_ready.is_set():
                    break
                if process.stdin is None:
                    break
                try:
                    process.stdin.write(chunk)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    # FFprobe puede cerrar el pipe tras reunir los metadatos.
                    break
            if process.stdin is not None:
                try:
                    process.stdin.write_eof()
                except (AttributeError, BrokenPipeError, ConnectionResetError, NotImplementedError):
                    pass
                if not process.stdin.is_closing():
                    process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=120)
            await reader
            await error_reader
        except Exception:
            if process.returncode is None:
                process.kill()
                await process.wait()
            reader.cancel()
            error_reader.cancel()
            await asyncio.gather(reader, error_reader, return_exceptions=True)
            raise
        finally:
            close_stream = getattr(stream, "aclose", None)
            if close_stream is not None:
                await close_stream()

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
            detail = stderr.decode(errors="replace").strip()[-300:]
            suffix = f" {detail}" if detail else ""
            raise VideoProcessingError(f"FFprobe no devolvió metadatos válidos.{suffix}") from error

    async def _run(client, message: Message) -> None:
        command = (message.command[0] if message.command else "").lower()
        args = list(message.command[1:] if message.command else [])
        quoted = message.reply_to_message
        if quoted is None:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return

        media = quoted.video or quoted.document
        if media is None:
            await message.reply_text("<b>Responde directamente a un video o documento de video.</b>", parse_mode=enums.ParseMode.HTML)
            return
        if quoted.document and not str(getattr(media, "mime_type", "")).startswith("video/"):
            suffix = Path(getattr(media, "file_name", "")).suffix.lower()
            if suffix not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}:
                await message.reply_text("<b>El documento citado no parece ser un video.</b>", parse_mode=enums.ParseMode.HTML)
                return

        doc = bool(args and args[-1].lower() == "doc")
        if doc:
            args.pop()
        if command == "dw" and args:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return
        if command in {"dw2", "dw3", "mi"} and not args:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return
        if command == "dw3" and len(args) != 3:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return
        if command == "mi" and len(args) != 2:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return
        if command == "dw4" and args:
            await message.reply_text(_usage(command), parse_mode=enums.ParseMode.HTML)
            return

        chat_id = message.chat.id
        if command != "dw" and chat_id in active_chats:
            await message.reply_text("⏳ <b>Ya hay un video procesándose en este chat.</b>", parse_mode=enums.ParseMode.HTML)
            return
        if command != "dw":
            active_chats.add(chat_id)

        if command == "dw":
            try:
                info = await _probe_streaming(client, quoted)
                await message.reply_text(_dw_html(info), parse_mode=enums.ParseMode.HTML)
            except Exception as error:
                logger.exception("Error analizando dw por streaming")
                detail = str(error).strip() or type(error).__name__
                await message.reply_text(f"❌ <b>No se pudo analizar el video:</b> {html.escape(detail)}", parse_mode=enums.ParseMode.HTML)
            return

        job_dir = Path(tempfile.mkdtemp(prefix="zerotwo-video-", dir=root))
        input_path = job_dir / f"input{safe_video_extension(getattr(media, 'file_name', ''), getattr(media, 'mime_type', None))}"
        output_path = job_dir / "output.mp4"
        status = None
        try:
            status = await message.reply_text("📥 <b>Descargando video…</b>", parse_mode=enums.ParseMode.HTML)
            await quoted.download(file_name=str(input_path))
            if not input_path.exists() or input_path.stat().st_size == 0:
                raise VideoProcessingError("Telegram no entregó un video válido.")
            info = await probe_video(input_path)

            resolution = 360 if command == "dw4" else _resolution(args[0])
            if resolution is None:
                await message.reply_text(f"❌ <b>Resolución válida:</b> {MIN_RESOLUTION}-{MAX_RESOLUTION}.\n{_usage(command)}", parse_mode=enums.ParseMode.HTML)
                return

            duration = float(info["duration"])
            two_pass_commands = None
            if command == "dw2":
                ffmpeg = build_compression_command(
                    input_path.name, output_path.name, crf=24,
                    scale=f"-2:{resolution}", threads=threads,
                )
                label = f"DW2 {resolution}p"
                filename = f"Video_{resolution}p.mp4"
            elif command == "dw4":
                input_mb = input_path.stat().st_size / 1024 / 1024
                target_mb = input_mb * 0.85
                if duration <= 0:
                    raise VideoProcessingError("No se pudo determinar la duración del video.")
                total_bits = target_mb * 1024 * 1024 * 8 * 0.94
                bitrate = max(100_000, int(total_bits / duration - 64_000))
                two_pass_commands = build_target_size_commands(
                    input_path.name, output_path.name, bitrate=bitrate,
                    threads=threads, passlog="dw4_twopass", scale="-2:360",
                )
                label = "DW4 360p · 2 pasadas"
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
                status_text = f"⚙️ <b>MI {resolution}p → {target_mb:g} MB</b>\nPasada 1/2…"
                await status.edit_text(status_text, parse_mode=enums.ParseMode.HTML)
                for index, ffmpeg in enumerate((first, second), 1):
                    if index == 2:
                        await status.edit_text(f"⚙️ <b>MI {resolution}p → {target_mb:g} MB</b>\nPasada 2/2…", parse_mode=enums.ParseMode.HTML)
                    await run_ffmpeg(
                        ffmpeg, cwd=job_dir, duration=duration,
                        progress_callback=lambda current, total: _progress(status, f"MI {resolution}p · pasada {index}/2", current, total),
                        timeout_seconds=timeout,
                        progress_label=f"MI {resolution}p · pasada {index}/2",
                    )
                filename = f"video_{resolution}p_{target_mb:g}mb.mp4"
                label = f"MI {resolution}p"

            if command == "dw4":
                await status.edit_text(f"⚙️ <b>{label}</b>\nPasada 1/2…", parse_mode=enums.ParseMode.HTML)
                for index, pass_command in enumerate(two_pass_commands, 1):
                    if index == 2:
                        await status.edit_text(f"⚙️ <b>{label}</b>\nPasada 2/2…", parse_mode=enums.ParseMode.HTML)
                    await run_ffmpeg(
                        pass_command, cwd=job_dir, duration=duration,
                        progress_callback=lambda current, total: _progress(status, f"{label} · pasada {index}/2", current, total),
                        timeout_seconds=timeout,
                        progress_label=f"{label} · pasada {index}/2",
                    )
            elif command != "mi":
                await status.edit_text(f"⚙️ <b>Procesando {label}…</b>", parse_mode=enums.ParseMode.HTML)
                await run_ffmpeg(
                    ffmpeg, cwd=job_dir, duration=duration,
                    progress_callback=lambda current, total: _progress(status, label, current, total),
                    timeout_seconds=timeout,
                    progress_label=label,
                )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise VideoProcessingError("FFmpeg no generó un archivo de salida.")

            size_mb = output_path.stat().st_size / 1024 / 1024
            caption = f"✅ {label} | {size_mb:.1f} MB"
            if doc:
                await message.reply_document(document=str(output_path), file_name=filename, caption=caption, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_video(video=str(output_path), caption=caption, supports_streaming=True, parse_mode=enums.ParseMode.HTML)
            await status.edit_text("✅ <b>Proceso terminado.</b>", parse_mode=enums.ParseMode.HTML)
        except (ValueError, VideoProcessingError) as error:
            if status:
                await status.edit_text(f"❌ <b>{html.escape(str(error))}</b>", parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text(f"❌ <b>{html.escape(str(error))}</b>", parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.exception("Error procesando %s", command)
            if status:
                await status.edit_text("❌ <b>Error al procesar el video.</b> Revisa el formato y vuelve a intentarlo.", parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("❌ <b>Error al procesar el video.</b>", parse_mode=enums.ParseMode.HTML)
        finally:
            active_chats.discard(chat_id)
            for path in job_dir.glob("*"):
                path.unlink(missing_ok=True)
            job_dir.rmdir()

    @app.on_message(filters.command(["dw", "dw2", "dw3", "dw4", "mi"]))
    async def video_processing_command(client, message: Message):
        await _run(client, message)
