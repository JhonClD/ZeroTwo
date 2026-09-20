"""
encoding_handler.py - Flujo de codificación heredado del ZIP, adaptado a ZeroTwo.
"""

import asyncio
import logging
import re
import shlex
import subprocess
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import Message
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm"}
_ENCODE_STATES = {}


def _encode_keyboard(user_id):
    s = _ENCODE_STATES[user_id]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎚 CRF {s['crf']}", callback_data=f"enc_menu:crf:{user_id}"), InlineKeyboardButton(f"⚡ {s['preset']}", callback_data=f"enc_menu:preset:{user_id}")],
        [InlineKeyboardButton(f"📊 Bitrate: {s['bitrate'] or 'CRF'}", callback_data=f"enc_menu:bitrate:{user_id}"), InlineKeyboardButton("🎧 Audio", callback_data=f"enc_menu:audio:{user_id}")],
        [InlineKeyboardButton("✅ Iniciar codificación", callback_data=f"enc_start:{user_id}"), InlineKeyboardButton("❌ Cancelar", callback_data=f"enc_cancel:{user_id}")],
    ])


def _safe_name(name: str) -> str:
    name = Path(name or "video.mkv").name
    return re.sub(r"[^\w.()\- ]+", "_", name)[:180] or "video.mkv"


def _parse_args(text: str):
    args = (text or "").split()
    crf, preset, bitrate, sub_idx, audio_idx = "23", "medium", None, None, None
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


def _run_logged(command, stage: str):
    """Ejecuta un proceso y refleja sus etapas/progreso en bot.log y en la terminal."""
    logger.info("▶️ INICIO | %s", stage)
    logger.info("🧰 COMANDO | %s", shlex.join(str(part) for part in command))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
    tail = []
    progress_lines = 0
    for raw_line in process.stderr:
        line = raw_line.strip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-20:]
        if "frame=" in line or "time=" in line or "speed=" in line:
            progress_lines += 1
            if progress_lines == 1 or progress_lines % 10 == 0:
                logger.info("📈 %s | %s", stage, line[-220:])
        elif "error" in line.lower() or "failed" in line.lower():
            logger.error("❌ %s | %s", stage, line[-500:])
    return_code = process.wait()
    if return_code == 0:
        logger.info("✅ FIN | %s | código=%s", stage, return_code)
    else:
        logger.error("❌ FIN ERROR | %s | código=%s", stage, return_code)
    return return_code, "\n".join(tail)


def _run_encode(input_path: Path, output_path: Path, two_pass=False, crf="23", preset="medium", bitrate=None, audio_idx=None, add_watermark=True):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("🎬 CODIFICACIÓN | entrada=%s salida=%s dos_pasadas=%s crf=%s preset=%s bitrate=%s audio=%s marca=%s", input_path, output_path, two_pass, crf, preset, bitrate, audio_idx, add_watermark)
    video_map = ["-map", "0:v:0"]
    audio_map = ["-map", f"0:a:{audio_idx}"] if audio_idx is not None else ["-map", "0:a:0?"]
    video_codec = ["-c:v", "libx264", "-preset", preset]
    video_quality = ["-b:v", bitrate] if bitrate else ["-crf", crf]
    common = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), *video_map, *audio_map]
    if add_watermark:
        common.extend(["-vf", _watermark_filter()])
    common.extend([*video_codec, *video_quality, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"])
    if not two_pass:
        rc, detail = _run_logged([*common, str(output_path)], "FFmpeg · codificación final")
        return rc == 0, detail

    passlog = output_path.with_suffix(".passlog")
    first = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), *video_map, "-an", *video_codec, *video_quality, "-pass", "1", "-passlogfile", str(passlog), "-f", "null", "/dev/null"]
    rc, detail = _run_logged(first, "FFmpeg · primera pasada")
    if rc != 0:
        return False, detail
    second = [*common, "-pass", "2", "-passlogfile", str(passlog), str(output_path)]
    rc, detail = _run_logged(second, "FFmpeg · segunda pasada")
    for suffix in ("", "-0.log", ".log"):
        Path(str(passlog) + suffix).unlink(missing_ok=True)
    return rc == 0, detail


async def _send_result(message: Message, output_path: Path, status: Message):
    logger.info("🖼️ MINIATURA | generando para %s", output_path)
    thumb_path = output_path.with_suffix(".jpg")
    duration, thumb = await asyncio.to_thread(VideoProcessor.get_video_meta, output_path, thumb_path)
    logger.info("📤 SUBIDA | archivo=%s duración=%s thumb=%s", output_path, duration, thumb)
    try:
        await message.reply_video(video=str(output_path), thumb=thumb, caption=f"✅ Codificación terminada\n🏷 ZeroTwo\n📄 {output_path.name}", duration=duration or None, supports_streaming=True)
        await status.delete()
        logger.info("✅ SUBIDA COMPLETADA | %s", output_path)
    finally:
        output_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        logger.info("🧹 LIMPIEZA | salida=%s miniatura=%s", output_path, thumb_path)


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
    logger.info("📥 DESCARGA | inicio=%s destino=%s", source_name, source)
    try:
        await reply.download(file_name=str(source))
        logger.info("✅ DESCARGA COMPLETADA | %s bytes=%s", source, source.stat().st_size)
        _ENCODE_STATES[message.from_user.id] = {"source": source, "output": output, "status": status, "two_pass": two_pass, "crf": "23", "preset": "veryfast", "bitrate": None, "audio": None}
        await status.edit_text("🎛 <b>Configura la codificación</b>\nElige calidad, velocidad y audio. Después pulsa iniciar.", reply_markup=_encode_keyboard(message.from_user.id), parse_mode=enums.ParseMode.HTML)
        return
    except Exception as error:
        logger.error("❌ ERROR CODIFICACIÓN | %s", error, exc_info=True)
        await status.edit_text(f"❌ Error codificando el video.\n<code>{str(error)[:500]}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        if message.from_user.id not in _ENCODE_STATES:
            source.unlink(missing_ok=True)
            logger.info("🧹 LIMPIEZA | fuente=%s", source)


def register(app, download_dir: Path):
    encoding_dir = Path(download_dir) / "zerotwo_encoding"
    encoded_dir = encoding_dir / "encoded"
    encoding_dir.mkdir(parents=True, exist_ok=True)
    encoded_dir.mkdir(parents=True, exist_ok=True)
    logger.info("📂 ENCODER LISTO | entrada=%s salida=%s", encoding_dir, encoded_dir)

    @app.on_callback_query(filters.regex(r"^enc_menu:(crf|preset|bitrate|audio):\d+$"))
    async def encode_menu(client, query):
        _, kind, uid = query.data.split(":"); uid = int(uid); state = _ENCODE_STATES.get(uid)
        if not state or query.from_user.id != uid: return await query.answer("Sesión expirada", show_alert=True)
        values = {"crf": ("18", "20", "23", "26", "28", "30"), "preset": ("ultrafast", "veryfast", "fast", "medium"), "bitrate": ("800k", "1200k", "2000k", "3500k", "6000k"), "audio": ("0", "1", "2")}[kind]
        buttons = [[InlineKeyboardButton(v, callback_data=f"enc_set:{kind}:{v}:{uid}") for v in values]]
        buttons.append([InlineKeyboardButton("↩️ Volver", callback_data=f"enc_back:{uid}")])
        await query.message.edit_text(f"Selecciona {kind}:", reply_markup=InlineKeyboardMarkup(buttons)); await query.answer()

    @app.on_callback_query(filters.regex(r"^enc_set:(crf|preset|bitrate|audio):[^:]+:\d+$"))
    async def encode_set(client, query):
        _, kind, value, uid = query.data.split(":"); state = _ENCODE_STATES.get(int(uid))
        if not state: return await query.answer("Sesión expirada", show_alert=True)
        state[kind] = int(value) if kind == "audio" else value
        if kind == "bitrate": state["crf"] = "23"
        await query.answer("Guardado"); await query.message.edit_text("🎛 <b>Configuración lista</b>", reply_markup=_encode_keyboard(int(uid)), parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^enc_back:\d+$"))
    async def encode_back(client, query):
        uid = int(query.data.split(":")[1])
        if uid in _ENCODE_STATES: await query.message.edit_text("🎛 <b>Configura la codificación</b>", reply_markup=_encode_keyboard(uid), parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^enc_start:\d+$"))
    async def encode_start(client, query):
        uid = int(query.data.split(":")[1]); state = _ENCODE_STATES.get(uid)
        if not state: return await query.answer("Sesión expirada", show_alert=True)
        await query.answer("Codificación iniciada"); await state["status"].edit_text("⚙️ Codificando con la configuración elegida…")
        ok, detail = await asyncio.to_thread(_run_encode, state["source"], state["output"], state["two_pass"], state["crf"], state["preset"], state["bitrate"], state["audio"])
        if ok: await _send_result(query.message, state["output"], state["status"])
        else: await state["status"].edit_text(f"❌ Error codificando: <code>{detail[:500]}</code>", parse_mode=enums.ParseMode.HTML)
        _ENCODE_STATES.pop(uid, None); state["source"].unlink(missing_ok=True)

    @app.on_callback_query(filters.regex(r"^enc_cancel:\d+$"))
    async def encode_cancel(client, query):
        uid = int(query.data.split(":")[1]); state = _ENCODE_STATES.pop(uid, None)
        if state: state["source"].unlink(missing_ok=True); await query.message.edit_text("❌ Codificación cancelada.")

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
        logger.info("📥 COLA LOCAL | inicio=%s destino=%s", name, destination)
        try:
            await reply.download(file_name=str(destination))
            logger.info("✅ COLA LOCAL | completado=%s bytes=%s", destination, destination.stat().st_size)
            await status.edit_text(f"✅ Guardado en la cola local:\n<code>{destination.name}</code>", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            logger.error("❌ ERROR DESCARGA LOCAL | %s", error, exc_info=True)
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
        logger.info("📦 COLA CODIFICACIÓN | archivos=%s modo=%s pista_sub=%s audio=%s", len(files), message.command[0], selected_sub_idx if use_subs else "no", audio_idx)
        status = await message.reply_text(f"⚙️ Codificando {len(files)} archivo(s) local(es)…")
        for source in files:
            output = encoded_dir / f"ZeroTwo_{source.stem}.mp4"
            try:
                source_for_encode = source
                if use_subs:
                    intermediate = encoding_dir / f"{source.stem}_sub.mp4"
                    logger.info("📝 QUEMADO INTERNO | fuente=%s pista=%s salida=%s", source, selected_sub_idx, intermediate)
                    ok = await VideoProcessor.burn_subtitles(source, None, intermediate, sub_idx=selected_sub_idx, is_external=False)
                    if not ok:
                        raise RuntimeError("No se pudo quemar la pista interna seleccionada")
                    source_for_encode = intermediate
                crf, preset, bitrate, _, parsed_audio = _parse_args(message.text)
                ok, detail = await asyncio.to_thread(_run_encode, source_for_encode, output, False, crf, preset, bitrate, parsed_audio if parsed_audio is not None else audio_idx, add_watermark=not (use_subs and source_for_encode != source))
                if source_for_encode != source:
                    source_for_encode.unlink(missing_ok=True)
                if not ok:
                    raise RuntimeError(detail or "FFmpeg falló")
                logger.info("✅ COLA COMPLETADA | fuente=%s salida=%s", source, output)
                await status.edit_text(f"✅ Codificado: <code>{output.name}</code>", parse_mode=enums.ParseMode.HTML)
            except Exception as error:
                logger.error("❌ ERROR COLA | fuente=%s error=%s", source, error, exc_info=True)
                await status.edit_text(f"❌ Error con {source.name}: <code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)
        await message.reply_text("📦 Usa /up2 para enviar los videos codificados.")

    @app.on_message(filters.command("up2"))
    async def upload_encoded(client, message: Message):
        files = list(encoded_dir.glob("*.mp4"))
        logger.info("📤 COLA SUBIDA | archivos=%s", len(files))
        if not files:
            await message.reply_text("⚠️ No hay videos codificados pendientes.")
            return
        for path in files:
            status = await message.reply_text(f"📤 Subiendo <code>{path.name}</code>…", parse_mode=enums.ParseMode.HTML)
            try:
                await _send_result(message, path, status)
            except Exception as error:
                logger.error("❌ ERROR SUBIDA | %s", error, exc_info=True)
                await status.edit_text(f"❌ Error subiendo: <code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("delete2"))
    async def delete_logs(client, message: Message):
        removed = []
        for path in encoding_dir.iterdir():
            if path.is_file() and path.suffix.lower() in {".log", ".ass", ".srt", ".vtt"}:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        logger.info("🧹 LIMPIEZA TEMPORALES | archivos=%s", removed)
        await message.reply_text("🗑️ Eliminados: " + (", ".join(removed) if removed else "no había temporales"))

    @app.on_message(filters.command("dele2"))
    async def delete_videos(client, message: Message):
        removed = []
        for path in encoding_dir.iterdir():
            if path.is_file() and path.suffix.lower() in _VIDEO_EXTENSIONS:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        logger.info("🧹 LIMPIEZA VIDEOS | archivos=%s", removed)
        await message.reply_text("🗑️ Eliminados: " + (", ".join(removed) if removed else "no había videos locales"))
