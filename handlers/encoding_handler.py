"""
encoding_handler.py - Flujo de codificación heredado del ZIP, adaptado a ZeroTwo.

Comandos:
  /dw2       Descarga el archivo al espacio local del bot.
  /press     Codifica un video respondido con CRF (por defecto 23).
  /press2    Codifica un video respondido con dos pasadas.
  /compre1   Alias de /press.
  /compress1 Alias de /press.
  /compre2   Alias de /press con -crf N.
  /compress2 Alias de /press2.
  /ed2       Codifica los MKV guardados localmente e intenta usar una pista de subtítulos.
  /ec2       Codifica los MKV guardados localmente sin subtítulos internos.
  /up2       Envía los videos codificados pendientes.
  /delete2   Elimina logs y subtítulos temporales.
  /dele2     Elimina videos locales temporales.

Los archivos se guardan dentro de DOWNLOAD_DIR/zerotwo_encoding.
"""

import asyncio
import logging
import re
import subprocess
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import Message

from utils.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm"}


def _safe_name(name: str) -> str:
    name = Path(name or "video.mkv").name
    return re.sub(r"[^\w.()\- ]+", "_", name)[:180] or "video.mkv"


def _parse_args(text: str):
    args = (text or "").split()
    crf = "23"
    preset = "medium"
    bitrate = None
    sub_idx = None
    audio_idx = None
    for index, arg in enumerate(args):
        if arg == "-crf" and index + 1 < len(args) and args[index + 1].isdigit():
            crf = str(max(16, min(35, int(args[index + 1]))))
        elif arg in {"-p", "-preset"} and index + 1 < len(args):
            preset = args[index + 1]
        elif arg in {"-vb", "-b:v"} and index + 1 < len(args):
            bitrate = args[index + 1]
        elif arg in {"-s", "-sub"} and index + 1 < len(args) and args[index + 1].isdigit():
            sub_idx = int(args[index + 1])
        elif arg in {"-a", "-audio"} and index + 1 < len(args) and args[index + 1].isdigit():
            audio_idx = int(args[index + 1])
    return crf, preset, bitrate, sub_idx, audio_idx


def _watermark_filter():
    return "drawtext=text='ZERO TWO':x=20:y=20:font='sans':fontsize=22:fontcolor=white:bordercolor=black:borderw=1.5:enable='lt(t,6)'"


def _run_encode(input_path: Path, output_path: Path, two_pass=False, crf="23", preset="medium", bitrate=None, audio_idx=None, add_watermark=True):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_map = ["-map", "0:v:0"]
    audio_map = ["-map", f"0:a:{audio_idx}"] if audio_idx is not None else ["-map", "0:a:0?"]
    video_codec = ["-c:v", "libx264", "-preset", preset]
    video_quality = ["-b:v", bitrate] if bitrate else ["-crf", crf]
    common = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), *video_map, *audio_map]
    if add_watermark:
        common.extend(["-vf", _watermark_filter()])
    common.extend([*video_codec, *video_quality, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"])
    if not two_pass:
        result = subprocess.run([*common, str(output_path)], capture_output=True, text=True, timeout=7200)
        return result.returncode == 0, result.stderr[-1200:]
    passlog = output_path.with_suffix(".passlog")
    first = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), *video_map, "-an", *video_codec, *video_quality, "-pass", "1", "-passlogfile", str(passlog), "-f", "null", "/dev/null"]
    first_result = subprocess.run(first, capture_output=True, text=True, timeout=7200)
    if first_result.returncode != 0:
        return False, first_result.stderr[-1200:]
    second = [*common, "-pass", "2", "-passlogfile", str(passlog), str(output_path)]
    second_result = subprocess.run(second, capture_output=True, text=True, timeout=7200)
    for suffix in ("", "-0.log", ".log"):
        Path(str(passlog) + suffix).unlink(missing_ok=True)
    return second_result.returncode == 0, second_result.stderr[-1200:]


async def _send_result(message: Message, output_path: Path, status: Message):
    thumb_path = output_path.with_suffix(".jpg")
    duration, thumb = await asyncio.to_thread(VideoProcessor.get_video_meta, output_path, thumb_path)
    try:
        await message.reply_video(video=str(output_path), thumb=thumb, caption=f"✅ Codificación terminada\n🏷 ZeroTwo\n📄 {output_path.name}", duration=duration or None, supports_streaming=True)
        await status.delete()
    finally:
        output_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)


async def _encode_reply(message: Message, encoding_dir: Path, two_pass=False):
    reply = message.reply_to_message
    media = (reply.video or reply.document) if reply else None
    if not media or (reply.document and not str(getattr(reply.document, "mime_type", "")).startswith("video/")):
        await message.reply_text("❌ Responde a un video o a un documento de video.")
        return
    source_name = _safe_name(getattr(media, "file_name", "video.mkv"))
    source = encoding_dir / f"source_{message.id}_{source_name}"
    output = encoding_dir / f"ZeroTwo_{Path(source_name).stem}.mp4"
    status = await message.reply_text("⏳ Descargando video para codificar…")
    try:
        await reply.download(file_name=str(source))
        crf, preset, bitrate, _, audio_idx = _parse_args(message.text)
        await status.edit_text(f"⚙️ Codificando {'en dos pasadas' if two_pass else 'con CRF'}…")
        ok, detail = await asyncio.to_thread(_run_encode, source, output, two_pass, crf, preset, bitrate, audio_idx)
        if not ok:
            raise RuntimeError(detail or "FFmpeg no pudo generar el archivo final")
        await _send_result(message, output, status)
    except Exception as error:
        logger.error("Error de codificación: %s", error, exc_info=True)
        await status.edit_text(f"❌ Error codificando el video.\n<code>{str(error)[:500]}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        source.unlink(missing_ok=True)


def register(app, download_dir: Path):
    encoding_dir = Path(download_dir) / "zerotwo_encoding"
    encoded_dir = encoding_dir / "encoded"
    encoding_dir.mkdir(parents=True, exist_ok=True)
    encoded_dir.mkdir(parents=True, exist_ok=True)

    @app.on_message(filters.command("dw2") & filters.reply)
    async def download_local(client, message: Message):
        reply = message.reply_to_message
        media = reply.document or reply.video or reply.audio
        if not media:
            await message.reply_text("❌ El mensaje respondido no contiene un archivo descargable.")
            return
        name = _safe_name(getattr(media, "file_name", "archivo"))
        destination = encoding_dir / name
        status = await message.reply_text(f"📥 Descargando localmente:\n<code>{name}</code>", parse_mode=enums.ParseMode.HTML)
        try:
            await reply.download(file_name=str(destination))
            await status.edit_text(f"✅ Guardado en la cola local:\n<code>{destination.name}</code>", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            await status.edit_text(f"❌ Error descargando: <code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command(["press", "compre1", "compress1"]) & filters.reply)
    async def encode_crf(client, message: Message):
        await _encode_reply(message, encoding_dir, two_pass=False)

    @app.on_message(filters.command(["press2", "compre2", "compress2"]) & filters.reply)
    async def encode_two_pass(client, message: Message):
        await _encode_reply(message, encoding_dir, two_pass=True)

    @app.on_message(filters.command(["ec2", "ed2"]))
    async def encode_local(client, message: Message):
        files = [p for p in encoding_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mkv"]
        if not files:
            await message.reply_text("⚠️ No hay archivos MKV en la cola local. Usa /dw2 respondiendo a un MKV.")
            return
        _, _, _, sub_idx, audio_idx = _parse_args(message.text)
        use_subs = message.command[0].lower() == "ed2"
        selected_sub_idx = sub_idx if sub_idx is not None else 0
        status = await message.reply_text(f"⚙️ Codificando {len(files)} archivo(s) local(es)…")
        for source in files:
            output = encoded_dir / f"ZeroTwo_{source.stem}.mp4"
            try:
                if use_subs and sub_idx is not None:
                    intermediate = encoding_dir / f"{source.stem}_sub.mp4"
                    ok = await VideoProcessor.burn_subtitles(source, None, intermediate, sub_idx=selected_sub_idx, is_external=False)
                    if not ok:
                        raise RuntimeError("No se pudo quemar la pista interna seleccionada")
                    source_for_encode = intermediate
                else:
                    source_for_encode = source
                crf, preset, bitrate, _, parsed_audio = _parse_args(message.text)
                ok, detail = await asyncio.to_thread(_run_encode, source_for_encode, output, False, crf, preset, bitrate, parsed_audio if parsed_audio is not None else audio_idx, add_watermark=not (use_subs and source_for_encode != source))
                if source_for_encode != source:
                    source_for_encode.unlink(missing_ok=True)
                if not ok:
                    raise RuntimeError(detail or "FFmpeg falló")
                await status.edit_text(f"✅ Codificado: <code>{output.name}</code>", parse_mode=enums.ParseMode.HTML)
            except Exception as error:
                await status.edit_text(f"❌ Error con {source.name}: <code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)
        await message.reply_text("📦 Usa /up2 para enviar los videos codificados.")

    @app.on_message(filters.command("up2"))
    async def upload_encoded(client, message: Message):
        files = list(encoded_dir.glob("*.mp4"))
        if not files:
            await message.reply_text("⚠️ No hay videos codificados pendientes.")
            return
        for path in files:
            status = await message.reply_text(f"📤 Subiendo <code>{path.name}</code>…", parse_mode=enums.ParseMode.HTML)
            try:
                await _send_result(message, path, status)
            except Exception as error:
                await status.edit_text(f"❌ Error subiendo: <code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("delete2"))
    async def delete_logs(client, message: Message):
        removed = []
        for path in encoding_dir.iterdir():
            if path.is_file() and path.suffix.lower() in {".log", ".ass", ".srt", ".vtt"}:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        await message.reply_text("🗑️ Eliminados: " + (", ".join(removed) if removed else "no había temporales"))

    @app.on_message(filters.command("dele2"))
    async def delete_videos(client, message: Message):
        removed = []
        for path in encoding_dir.iterdir():
            if path.is_file() and path.suffix.lower() in _VIDEO_EXTENSIONS:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        await message.reply_text("🗑️ Eliminados: " + (", ".join(removed) if removed else "no había videos locales"))
