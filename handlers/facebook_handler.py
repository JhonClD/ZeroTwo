"""
facebook_handler.py - Manejador de descargas de Facebook
Usa exclusivamente loader.to para resolver videos de Facebook
"""

import asyncio
import logging
import re
import subprocess
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from utils import VideoProcessor
from utils.loader_to import (
    LoaderToError,
    download_url as loader_download_url,
    get_available_formats,
)

logger = logging.getLogger(__name__)


async def _safe_edit(message: Message, text: str, **kwargs):
    """Edita un mensaje sin fallar si Telegram ya contiene el mismo texto."""
    if getattr(message, "text", None) == text and "reply_markup" not in kwargs:
        return
    try:
        await message.edit_text(text, **kwargs)
    except Exception as error:
        if "MESSAGE_NOT_MODIFIED" not in str(error):
            raise
        logger.debug("Mensaje de estado sin cambios; se ignora MESSAGE_NOT_MODIFIED")


def _format_quality(item: dict[str, str]) -> str:
    label = str(item.get("label", item.get("format", ""))).strip()
    return label if re.search(r"\d+\s*p\b", label, re.IGNORECASE) or label.lower().endswith(("mp3", "kbps")) else f"{label}p"


def register(app, download_dir):
    """Registra el handler de Facebook."""
    pending_quality: dict[int, tuple[Message, str, list[dict[str, str]], Message]] = {}

    async def download_and_send(request_message: Message, fb_link: str, media_format: str, status_msg: Message):
        output_file = download_dir / f"fb_{request_message.from_user.id}_{request_message.id}.mp4"
        tmp_fb_thumb = download_dir / f"fb_{request_message.from_user.id}_{request_message.id}_thumb.jpg"
        try:
            await _safe_edit(status_msg, "⏳ Solicitando video a loader.to...")
            video_url, video_title = await loader_download_url(fb_link, media_format)
            logger.info("✅ loader.to devolvió una URL de Facebook en formato %s", media_format)

            await _safe_edit(status_msg, "📥 Descargando video...")
            dl_cmd = ["curl", "-sS", "-L", "--fail", "--max-time", "300", "-o", str(output_file), video_url]
            dl_result = subprocess.run(dl_cmd, timeout=320)
            if dl_result.returncode != 0 or not output_file.exists() or output_file.stat().st_size < 10_000:
                raise RuntimeError("Error descargando el video desde loader.to")

            file_size = output_file.stat().st_size / (1024 * 1024)
            await _safe_edit(status_msg, "📤 Enviando video...")
            caption = "✅ <b>Video de Facebook</b>"
            if video_title:
                caption = f"✅ <b>{video_title}</b>"

            last_percent = [-10]

            async def upload_progress(current, total):
                if not total:
                    return
                percent = int(current / total * 100)
                if percent - last_percent[0] >= 10:
                    logger.info("📤 Subida: %s%% (%.1f/%.1f MB)", percent, current / 2**20, total / 2**20)
                    last_percent[0] = percent

            fb_duration, fb_thumb = VideoProcessor.get_video_meta(output_file, tmp_fb_thumb)
            await request_message.reply_video(
                video=str(output_file),
                caption=f"{caption}\n📦 {file_size:.2f} MB\n🎞 Calidad: {media_format}",
                parse_mode=enums.ParseMode.HTML,
                supports_streaming=True,
                progress=upload_progress,
                duration=fb_duration or None,
                thumb=fb_thumb,
            )
            await status_msg.delete()
        finally:
            output_file.unlink(missing_ok=True)
            tmp_fb_thumb.unlink(missing_ok=True)

    @app.on_message(filters.command(["fb", "facebook", "fbdl"]))
    async def facebook_command(client, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text(
                "📘 <b>Facebook Downloader</b>\n\n"
                "⚠️ Ingresa un enlace de Facebook.\n\n"
                "<b>Ejemplo:</b>\n<code>/fb https://www.facebook.com/watch/?v=12345</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        fb_link = args[1].strip()
        if not re.search(r"facebook\.com|fb\.watch", fb_link, re.IGNORECASE):
            await message.reply_text("❌ El enlace no parece ser de Facebook.")
            return

        status_msg = await message.reply_text("🔎 Consultando calidades disponibles en loader.to...")
        try:
            formats = await asyncio.to_thread(get_available_formats, fb_link)
            if not formats:
                formats = [{"format": "720", "label": "720p (predeterminada)"}]

            # Telegram permite hasta 100 botones; se limita para no saturar el mensaje.
            formats = formats[:10]
            buttons = [
                [InlineKeyboardButton(_format_quality(item), callback_data=f"fbq:{message.from_user.id}:{index}")]
                for index, item in enumerate(formats)
            ]
            pending_quality[message.from_user.id] = (message, fb_link, formats, status_msg)
            await _safe_edit(
                status_msg,
                "🎞 <b>Elige la calidad disponible:</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        except Exception as error:
            logger.warning("No se pudieron consultar las calidades; se usa 720p: %s", error)
            try:
                await download_and_send(message, fb_link, "720", status_msg)
            except Exception as download_error:
                logger.error("❌ Error en Facebook: %s", download_error, exc_info=True)
                await _safe_edit(status_msg, f"❌ <b>Error:</b> {download_error}", parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^fbq:\d+:\d+$"))
    async def facebook_quality_callback(client, callback_query):
        try:
            _, owner_id, index_text = callback_query.data.split(":")
            owner_id, index = int(owner_id), int(index_text)
            if callback_query.from_user.id != owner_id:
                await callback_query.answer("Esta selección pertenece a otro usuario.", show_alert=True)
                return
            pending = pending_quality.pop(owner_id, None)
            if not pending:
                await callback_query.answer("La selección expiró. Envía el comando nuevamente.", show_alert=True)
                return
            request_message, fb_link, formats, status_msg = pending
            if index >= len(formats):
                await callback_query.answer("Calidad no disponible.", show_alert=True)
                return
            media_format = formats[index]["format"]
            await callback_query.answer(f"Descargando {_format_quality(formats[index])}...")
            await _safe_edit(status_msg, f"⏳ Preparando {_format_quality(formats[index])}...")
            try:
                await download_and_send(request_message, fb_link, media_format, status_msg)
            except Exception as error:
                logger.error("❌ Error en Facebook: %s", error, exc_info=True)
                await _safe_edit(status_msg, f"❌ <b>Error:</b> {error}", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            logger.error("❌ Error seleccionando calidad de Facebook: %s", error, exc_info=True)
            await callback_query.answer("No se pudo procesar la selección.", show_alert=True)
