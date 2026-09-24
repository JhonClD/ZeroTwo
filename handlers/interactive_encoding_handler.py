"""Flujo interactivo de codificación inspirado en el ZIP."""

import asyncio
import logging
import uuid
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from utils.video_processor import VideoProcessor
from handlers.encoding_handler import _run_encode, _safe_name, _parse_args

logger = logging.getLogger(__name__)
_pending = {}


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else message.chat.id


def _buttons(prefix: str, user_id: int, options):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"enc:{user_id}:{prefix}:{value}")]
        for value, label in options
    ])


def _audio_options(media_info):
    tracks = media_info.get("audio", []) if media_info else []
    if not tracks:
        return [("none", "🔇 Sin audio")]
    return [(str(index), track.get("label", f"Audio {index}")) for index, track in enumerate(tracks[:12])]


def _subtitle_options(media_info):
    tracks = media_info.get("subtitle", []) if media_info else []
    options = [("none", "🚫 Sin subtítulos")]
    options.extend((str(track["index"]), track.get("label", f"Subtítulos {track['index']}")) for track in tracks[:12])
    return options


async def _run_selected(message: Message, state: dict):
    status = state["status"]
    input_path = Path(state["input_path"])
    job_dir = Path(state["job_dir"])
    output_path = job_dir / f"ZeroTwo_{input_path.stem}.mp4"
    subtitle_index = state["subtitle"]
    intermediate = None
    try:
        await status.edit_text("⚙️ <b>Configuración recibida.</b>\nIniciando procesos…", parse_mode=enums.ParseMode.HTML)
        source_for_encode = input_path
        add_watermark = True
        if subtitle_index != "none":
            intermediate = job_dir / f"{input_path.stem}_sub.mp4"
            logger.info("📝 INTERACTIVO | quemando pista interna=%s", subtitle_index)
            ok = await VideoProcessor.burn_subtitles(input_path, None, intermediate, sub_idx=int(subtitle_index), is_external=False)
            if not ok:
                raise RuntimeError("No se pudo quemar la pista de subtítulos seleccionada")
            source_for_encode = intermediate
            add_watermark = False

        scale = None if state["resolution"] == "original" else state["resolution"]
        audio_idx = None if state["audio"] == "none" else int(state["audio"])
        two_pass = state["mode"] == "2pass"
        logger.info("🎛️ INTERACTIVO | resolución=%s audio=%s subtítulos=%s modo=%s", scale, audio_idx, subtitle_index, state["mode"])
        ok, detail = await asyncio.to_thread(
            _run_encode,
            source_for_encode,
            output_path,
            two_pass,
            state["crf"],
            "medium",
            None,
            audio_idx,
            add_watermark,
            scale,
        )
        if not ok:
            raise RuntimeError(detail or "FFmpeg no pudo generar el resultado")
        thumb = output_path.with_suffix(".jpg")
        duration, thumb_result = await asyncio.to_thread(VideoProcessor.get_video_meta, output_path, thumb)
        await message.reply_video(
            video=str(output_path),
            thumb=thumb_result,
            caption=f"✅ Codificación terminada\n🎛 Resolución: {state['resolution']}\n🎧 Audio: {state['audio']}\n📝 Subtítulos: {subtitle_index}\n🏷 ZeroTwo",
            duration=duration or None,
            supports_streaming=True,
        )
        await status.delete()
        thumb.unlink(missing_ok=True)
    except Exception as error:
        logger.error("❌ INTERACTIVO | error=%s", error, exc_info=True)
        await status.edit_text(f"❌ Error durante la codificación.\n<code>{str(error)[:500]}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        _pending.pop(state["user_id"], None)
        for path in job_dir.glob("*"):
            path.unlink(missing_ok=True)
        job_dir.rmdir()


def register(app, work_dir: Path):
    @app.on_message(filters.command(["press", "press2", "compre1", "compress1", "compre2", "compress2"]) & filters.reply)
    async def start_interactive(client, message: Message):
        reply = message.reply_to_message
        media = (reply.video or reply.document) if reply else None
        if not media or (reply.document and not str(getattr(reply.document, "mime_type", "")).startswith("video/")):
            await message.reply_text("❌ Responde a un video o documento de video.")
            return
        user_id = _uid(message)
        job_dir = Path(work_dir) / f"interactive_{user_id}_{uuid.uuid4().hex[:8]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        source_name = _safe_name(getattr(media, "file_name", "video.mkv"))
        input_path = job_dir / source_name
        status = await message.reply_text("⏳ Descargando y analizando el video…")
        state = {
            "user_id": user_id,
            "request": message,
            "status": status,
            "job_dir": str(job_dir),
            "input_path": str(input_path),
            "mode": "2pass" if message.command[0].lower() in {"press2", "compre2", "compress2"} else "crf",
            "crf": "23",
        }
        _pending[user_id] = state
        try:
            logger.info("🎛️ INTERACTIVO | descarga=%s", input_path)
            await reply.download(file_name=str(input_path))
            info = await asyncio.to_thread(VideoProcessor.probe_media, input_path)
            state["media_info"] = info or {}
            await status.edit_text("🎞 <b>Elige la resolución:</b>", reply_markup=_buttons("q", user_id, [("original", "Original"), ("1280:720", "720p"), ("1920:1080", "1080p")]), parse_mode=enums.ParseMode.HTML)
            logger.info("🎛️ INTERACTIVO | video analizado audio=%s subtítulos=%s", len(state["media_info"].get("audio", [])), len(state["media_info"].get("subtitle", [])))
        except Exception as error:
            logger.error("❌ INTERACTIVO | descarga/análisis: %s", error, exc_info=True)
            _pending.pop(user_id, None)
            await status.edit_text(f"❌ No se pudo analizar el video.\n<code>{str(error)[:400]}</code>", parse_mode=enums.ParseMode.HTML)
            for path in job_dir.glob("*"):
                path.unlink(missing_ok=True)
            job_dir.rmdir()

    @app.on_callback_query(filters.regex(r"^enc:\d+:[qasm]:.+$"))
    async def interactive_callback(client, callback_query):
        try:
            _, owner_text, stage, value = callback_query.data.split(":", 3)
            owner_id = int(owner_text)
            if callback_query.from_user.id != owner_id:
                await callback_query.answer("Esta selección pertenece a otro usuario.", show_alert=True)
                return
            state = _pending.get(owner_id)
            if not state:
                await callback_query.answer("La configuración expiró.", show_alert=True)
                return
            await callback_query.answer("Selección guardada")
            status = state["status"]
            if stage == "q":
                state["resolution"] = value
                await status.edit_text("🎧 <b>Elige la pista de audio:</b>", reply_markup=_buttons("a", owner_id, _audio_options(state["media_info"])), parse_mode=enums.ParseMode.HTML)
            elif stage == "a":
                state["audio"] = value
                await status.edit_text("📝 <b>Elige la pista de subtítulos:</b>", reply_markup=_buttons("s", owner_id, _subtitle_options(state["media_info"])), parse_mode=enums.ParseMode.HTML)
            elif stage == "s":
                state["subtitle"] = value
                await status.edit_text("⚙️ <b>Elige el modo de codificación:</b>", reply_markup=_buttons("m", owner_id, [("crf23", "CRF 23 · rápido"), ("crf28", "CRF 28 · menor tamaño"), ("2pass", "2 pasadas · calidad")]), parse_mode=enums.ParseMode.HTML)
            elif stage == "m":
                state["mode"] = "2pass" if value == "2pass" else "crf"
                state["crf"] = "28" if value == "crf28" else "23"
                await _run_selected(callback_query.message, state)
        except Exception as error:
            logger.error("❌ INTERACTIVO | callback: %s", error, exc_info=True)
            await callback_query.answer("No se pudo procesar la selección.", show_alert=True)
