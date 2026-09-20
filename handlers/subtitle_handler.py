"""
subtitle_handler.py - Quemado de subtítulos sobre videos.

Uso:
1. Responde a un video con /sub.
2. Envía un archivo .srt, .ass o .vtt.
3. El bot devuelve el video con los subtítulos quemados y la marca ZeroTwo.
"""

import logging
import uuid
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import Message

from utils.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt"}


def _media_name(message: Message) -> str:
    media = message.video or message.document
    return getattr(media, "file_name", "video") if media else "video"


def register(app, user_states, work_dir: Path):
    """Registra /sub y el receptor del archivo de subtítulos."""

    @app.on_message(filters.command("sub"))
    async def subtitle_command(client, message: Message):
        reply = message.reply_to_message
        if not reply or not (reply.video or reply.document):
            await message.reply_text(
                "📝 Responde a un video con <code>/sub</code> y después envíame el archivo "
                "de subtítulos (.srt, .ass o .vtt).",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        user_id = message.from_user.id if message.from_user else message.chat.id
        user_states[user_id] = {"action": "burn_subtitles", "video_message": reply}
        await message.reply_text(
            "✅ Video seleccionado. Ahora envíame el archivo de subtítulos "
            "<code>.srt</code>, <code>.ass</code> o <code>.vtt</code>.",
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.document)
    async def subtitle_document(client, message: Message):
        user_id = message.from_user.id if message.from_user else message.chat.id
        state = user_states.get(user_id, {})
        if state.get("action") != "burn_subtitles":
            return

        subtitle_name = getattr(message.document, "file_name", "") or "subtitles.srt"
        subtitle_ext = Path(subtitle_name).suffix.lower()
        if subtitle_ext not in _SUBTITLE_EXTENSIONS:
            await message.reply_text("❌ El archivo debe ser .srt, .ass o .vtt.")
            return

        user_states.pop(user_id, None)
        video_message = state["video_message"]
        job_dir = Path(work_dir) / f"subtitle_{user_id}_{uuid.uuid4().hex[:8]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        video_path = job_dir / _media_name(video_message)
        subtitle_path = job_dir / subtitle_name
        output_path = job_dir / f"{video_path.stem}_ZeroTwo.mp4"
        status = await message.reply_text("⏳ Preparando el video y los subtítulos…")

        async def progress_update(text):
            try:
                await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
            except Exception:
                logger.debug("No se pudo actualizar el progreso de subtítulos", exc_info=True)

        try:
            await video_message.download(file_name=str(video_path))
            await message.download(file_name=str(subtitle_path))
            await status.edit_text("📝 <b>Quemando subtítulos…</b>\nEsto puede tardar según la duración del video.", parse_mode=enums.ParseMode.HTML)
            success = await VideoProcessor.burn_subtitles(
                video_path,
                subtitle_path,
                output_path,
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
        except Exception as error:
            logger.error("Error en /sub: %s", error, exc_info=True)
            await status.edit_text(f"❌ No se pudieron quemar los subtítulos.\n<code>{str(error)[:300]}</code>", parse_mode=enums.ParseMode.HTML)
        finally:
            for file_path in job_dir.glob("*"):
                file_path.unlink(missing_ok=True)
            job_dir.rmdir()
