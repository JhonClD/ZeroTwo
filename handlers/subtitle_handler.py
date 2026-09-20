"""
subtitle_handler.py - Quemado de subtítulos sobre videos.

Uso:
1. Responde a un video con /sub.
2. Si el video tiene pistas internas, el bot muestra botones para elegir una.
3. Si no tiene pistas internas, o se prefiere una externa, envía .srt, .ass o .vtt.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from utils.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt"}


def _media_name(message: Message) -> str:
    media = message.video or message.document
    return getattr(media, "file_name", "video.mkv") if media else "video.mkv"


def _user_id(message: Message) -> int:
    return message.from_user.id if message.from_user else message.chat.id


def _cleanup_job(state: dict):
    job_dir = Path(state["job_dir"])
    for file_path in job_dir.glob("*"):
        file_path.unlink(missing_ok=True)
    job_dir.rmdir()


async def _burn_and_send(message: Message, state: dict, subtitle_path=None, sub_idx=None):
    video_path = Path(state["video_path"])
    output_path = Path(state["job_dir"]) / f"{video_path.stem}_ZeroTwo.mp4"
    status = state["status"]
    logger.info("📝 QUEMADO | entrada=%s externo=%s pista_interna=%s salida=%s", video_path, subtitle_path, sub_idx, output_path)

    async def progress_update(text):
        try:
            await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.debug("No se pudo actualizar el progreso de subtítulos", exc_info=True)

    try:
        await status.edit_text(
            "📝 <b>Quemando subtítulos…</b>\nEsto puede tardar según la duración del video.",
            parse_mode=enums.ParseMode.HTML,
        )
        success = await VideoProcessor.burn_subtitles(
            video_path,
            subtitle_path,
            output_path,
            sub_idx=sub_idx,
            is_external=subtitle_path is not None,
            progress_callback=progress_update,
        )
        if not success:
            raise RuntimeError("FFmpeg no pudo generar el video final.")

        await message.reply_video(
            video=str(output_path),
            caption="✅ Subtítulos quemados correctamente\n🏷 Marca: ZeroTwo",
            supports_streaming=True,
        )
        await status.delete()
        logger.info("✅ QUEMADO COMPLETADO | salida=%s bytes=%s", output_path, output_path.stat().st_size)
    except Exception as error:
        logger.error("Error quemando subtítulos: %s", error, exc_info=True)
        await status.edit_text(
            f"❌ No se pudieron quemar los subtítulos.\n<code>{str(error)[:300]}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    finally:
        user_states = state["user_states"]
        user_states.pop(state["user_id"], None)
        _cleanup_job(state)
        logger.info("🧹 LIMPIEZA SUBTÍTULOS | carpeta=%s", state["job_dir"])


def register(app, user_states, work_dir: Path):
    """Registra /sub, la selección de pistas internas y archivos externos."""

    @app.on_message(filters.command("sub"))
    async def subtitle_command(client, message: Message):
        reply = message.reply_to_message
        if not reply or not (reply.video or reply.document):
            await message.reply_text(
                "📝 Responde a un video con <code>/sub</code>.\n"
                "Si el video tiene varias pistas, podrás elegir una.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        user_id = _user_id(message)
        job_dir = Path(work_dir) / f"subtitle_{user_id}_{uuid.uuid4().hex[:8]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        video_path = job_dir / _media_name(reply)
        status = await message.reply_text("⏳ Descargando y analizando las pistas del video…")
        logger.info("📥 SUBTÍTULOS | inicio usuario=%s fuente=%s destino=%s", user_id, _media_name(reply), video_path)
        state = {
            "action": "burn_subtitles",
            "video_message": reply,
            "video_path": str(video_path),
            "job_dir": str(job_dir),
            "status": status,
            "user_id": user_id,
            "user_states": user_states,
        }
        user_states[user_id] = state

        try:
            await reply.download(file_name=str(video_path))
            logger.info("✅ SUBTÍTULOS | descarga completada archivo=%s bytes=%s", video_path, video_path.stat().st_size)
            media_info = await asyncio.to_thread(VideoProcessor.probe_media, video_path)
            subtitle_tracks = (media_info or {}).get("subtitle", [])
            logger.info("🔎 PISTAS SUBTÍTULOS | archivo=%s cantidad=%s pistas=%s", video_path, len(subtitle_tracks), subtitle_tracks)
            if subtitle_tracks:
                buttons = []
                for track in subtitle_tracks[:20]:
                    label = track.get("label", f"Pista {track['index']}")[:55]
                    buttons.append([InlineKeyboardButton(label, callback_data=f"sub_internal:{user_id}:{track['index']}")])
                await status.edit_text(
                    "🎞 <b>El video tiene varias pistas de subtítulos.</b>\n"
                    "Elige cuál quieres quemar:\n\n"
                    "También puedes enviarme un archivo .srt, .ass o .vtt para usar uno externo.",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await status.edit_text(
                    "✅ No encontré subtítulos internos.\n"
                    "Ahora envíame un archivo <code>.srt</code>, <code>.ass</code> o <code>.vtt</code>.",
                    parse_mode=enums.ParseMode.HTML,
                )
        except Exception as error:
            user_states.pop(user_id, None)
            _cleanup_job(state)
            await status.edit_text(f"❌ No se pudo analizar el video.\n<code>{str(error)[:300]}</code>", parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^sub_internal:\d+:\d+$"))
    async def subtitle_track_selected(client, callback_query):
        user_id = callback_query.from_user.id
        try:
            _, callback_user_id, track_index = callback_query.data.split(":")
            if int(callback_user_id) != user_id:
                await callback_query.answer("Esta selección pertenece a otro usuario.", show_alert=True)
                return
            state = user_states.get(user_id)
            if not state or state.get("action") != "burn_subtitles":
                await callback_query.answer("La sesión de subtítulos ya expiró.", show_alert=True)
                return
            await callback_query.answer("Pista seleccionada")
            await callback_query.message.edit_text("✅ Pista seleccionada. Iniciando procesamiento…")
            logger.info("🎯 PISTA SELECCIONADA | usuario=%s pista=%s", user_id, track_index)
            await _burn_and_send(callback_query.message, state, sub_idx=int(track_index))
        except Exception as error:
            logger.error("Error seleccionando pista de subtítulos: %s", error, exc_info=True)
            await callback_query.answer("No se pudo seleccionar esa pista.", show_alert=True)

    @app.on_message(filters.document)
    async def subtitle_document(client, message: Message):
        user_id = _user_id(message)
        state = user_states.get(user_id, {})
        if state.get("action") != "burn_subtitles":
            return

        subtitle_name = getattr(message.document, "file_name", "") or "subtitles.srt"
        subtitle_ext = Path(subtitle_name).suffix.lower()
        if subtitle_ext not in _SUBTITLE_EXTENSIONS:
            await message.reply_text("❌ El archivo debe ser .srt, .ass o .vtt.")
            return

        subtitle_path = Path(state["job_dir"]) / subtitle_name
        try:
            await message.download(file_name=str(subtitle_path))
            logger.info("✅ SUBTÍTULO EXTERNO | archivo=%s bytes=%s", subtitle_path, subtitle_path.stat().st_size)
            await _burn_and_send(message, state, subtitle_path=subtitle_path)
        except Exception as error:
            logger.error("Error recibiendo subtítulos externos: %s", error, exc_info=True)
            user_states.pop(user_id, None)
            _cleanup_job(state)
            await message.reply_text(f"❌ No se pudo descargar el archivo de subtítulos.\n<code>{str(error)[:300]}</code>", parse_mode=enums.ParseMode.HTML)
