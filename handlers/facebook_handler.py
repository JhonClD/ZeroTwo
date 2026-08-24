"""
facebook_handler.py - Descargas directas de Facebook mediante loader.to.
"""

import logging
import re
import subprocess

from pyrogram import enums, filters
from pyrogram.types import Message

from utils.loader_to import LoaderToError, download_url as loader_download_url

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


def register(app, download_dir):
    """Registra el handler de Facebook."""

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

        status_msg = await message.reply_text("⏳ Descargando video de Facebook con loader.to...")
        output_file = download_dir / f"fb_{message.from_user.id}_{message.id}.mp4"
        try:
            video_url, video_title = await loader_download_url(fb_link, "720")
            await _safe_edit(status_msg, "📥 Descargando video...")
            result = subprocess.run(
                ["curl", "-sS", "-L", "--fail", "--max-time", "300", "-o", str(output_file), video_url],
                timeout=320,
            )
            if result.returncode != 0 or not output_file.exists() or output_file.stat().st_size < 10_000:
                raise RuntimeError("Error descargando el video desde loader.to")

            await _safe_edit(status_msg, "📤 Enviando video...")
            caption = "✅ <b>Video de Facebook</b>"
            if video_title:
                caption = f"✅ <b>{video_title}</b>"
            await message.reply_video(
                video=str(output_file),
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                supports_streaming=True,
            )
            await status_msg.delete()
        except LoaderToError as error:
            logger.error("❌ loader.to no pudo procesar Facebook: %s", error)
            await _safe_edit(status_msg, f"❌ <b>Error:</b> {error}", parse_mode=enums.ParseMode.HTML)
        except subprocess.TimeoutExpired:
            await _safe_edit(status_msg, "⏱️ La descarga tardó demasiado. Intenta de nuevo.")
        except Exception as error:
            logger.error("❌ Error en Facebook: %s", error, exc_info=True)
            await _safe_edit(status_msg, f"❌ <b>Error:</b> {error}", parse_mode=enums.ParseMode.HTML)
        finally:
            output_file.unlink(missing_ok=True)
