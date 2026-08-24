"""
url_handler.py - Manejador de URLs (MEGA / MediaFire)
Muestra barra de progreso en Telegram y en terminal durante descarga y envío.
"""

import re
import logging
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message
from downloaders import MEGADownloader, MediaFireDownloader
from downloaders.drive_downloader import DriveDownloader

logger = logging.getLogger(__name__)

VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v'}
AUDIO_EXTS = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return '▓' * filled + '░' * (width - filled)


def register(app, download_dir):
    """Registra el handler de URLs."""

    @app.on_message(filters.text & filters.regex(r'https?://'))
    async def handle_url(client, message: Message):
        url      = message.text.strip()
        user_id  = message.from_user.id
        username = message.from_user.username or message.from_user.first_name

        logger.info(f"🔗 URL de @{username}: {url[:80]}")

        is_mega      = MEGADownloader.is_mega_url(url)
        is_mediafire = MediaFireDownloader.is_mediafire_url(url)
        is_drive     = DriveDownloader.is_drive_url(url)

        if not any([is_mega, is_mediafire, is_drive]):
            logger.info("⏭️ URL ignorada (no es MEGA, MediaFire ni Drive)")
            return

        if is_mega:
            service = "MEGA"
        elif is_mediafire:
            service = "MediaFire"
        else:
            service = "Google Drive"

        logger.info(f"✅ Servicio: {service}")

        user_dir = download_dir / f"user_{user_id}"
        user_dir.mkdir(exist_ok=True)

        status_msg = await message.reply_text(
            f"📥 <b>Iniciando descarga desde {service}…</b>",
            parse_mode=enums.ParseMode.HTML
        )

        # ── Callback de progreso → Telegram ──────────────────────────────────
        async def tg_progress(text: str):
            try:
                await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        # ── Descarga ──────────────────────────────────────────────────────────
        try:
            if is_mega:
                success, file_path, error = await MEGADownloader.download(url, user_dir, tg_progress)
            elif is_mediafire:
                success, file_path, error = await MediaFireDownloader.download(url, user_dir, tg_progress)
            else:
                success, file_path, error = await DriveDownloader.download(url, user_dir, tg_progress)

            if not success:
                await status_msg.edit_text(
                    f"❌ <b>Error descargando de {service}</b>\n\n{error}",
                    parse_mode=enums.ParseMode.HTML
                )
                return

            file_size = file_path.stat().st_size / (1024 * 1024)
            file_ext  = file_path.suffix.lower()
            filename  = file_path.name

            logger.info(f"✅ Descarga completa: {filename} ({file_size:.1f} MB)")

            await status_msg.edit_text(
                f"✅ <b>Descarga completada</b>\n"
                f"📄 {filename}\n"
                f"📦 {file_size:.1f} MB\n"
                f"📤 Enviando a Telegram…",
                parse_mode=enums.ParseMode.HTML
            )

            # ── Progreso de envío a Telegram ──────────────────────────────────
            last_pct = [-10]

            async def send_progress(current, total):
                pct = int(current / total * 100)
                if pct - last_pct[0] >= 10:
                    mb_c = current / (1024 ** 2)
                    mb_t = total   / (1024 ** 2)
                    bar  = _progress_bar(pct)
                    logger.info(f"📤 Enviando {pct}% ({mb_c:.1f}/{mb_t:.1f} MB)")
                    try:
                        await status_msg.edit_text(
                            f"📤 <b>Enviando a Telegram</b>\n"
                            f"📄 {filename}\n"
                            f"{bar} {pct}%\n"
                            f"💾 {mb_c:.1f} / {mb_t:.1f} MB",
                            parse_mode=enums.ParseMode.HTML
                        )
                    except Exception:
                        pass
                    last_pct[0] = pct

            # ── Enviar archivo ────────────────────────────────────────────────
            caption = f"✅ Descargado de {service}\n📄 {filename}"

            try:
                if file_ext in VIDEO_EXTS:
                    logger.info("🎬 Enviando como video…")
                    await message.reply_video(
                        video=str(file_path), caption=caption,
                        supports_streaming=True, progress=send_progress,
                    )
                elif file_ext in AUDIO_EXTS:
                    logger.info("🎵 Enviando como audio…")
                    await message.reply_audio(
                        audio=str(file_path), caption=caption, progress=send_progress
                    )
                elif file_ext in IMAGE_EXTS:
                    logger.info("🖼️ Enviando como imagen…")
                    await message.reply_photo(
                        photo=str(file_path), caption=caption, progress=send_progress
                    )
                else:
                    logger.info(f"📄 Enviando como documento: {filename}")
                    await message.reply_document(
                        document=str(file_path), caption=caption, progress=send_progress
                    )

                logger.info("✅ Archivo enviado exitosamente")
                await status_msg.delete()

            except Exception as e:
                logger.error(f"❌ Error enviando archivo: {e}")
                await status_msg.edit_text(
                    "❌ Error enviando el archivo.\n"
                    "Puede ser que el archivo sea demasiado grande para Telegram."
                )

            file_path.unlink(missing_ok=True)
            logger.info("🗑️ Archivo temporal eliminado")

        except Exception as e:
            logger.error(f"❌ Error en handle_url: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Error</b>\n{str(e)[:200]}",
                parse_mode=enums.ParseMode.HTML
            )
