"""
drive_handler.py - Descarga desde Google Drive, subida a Drive y screenshots de video
Comandos: /gdrive <url_o_id>  |  /gdrive_upload (luego enviar archivo)  |  /gdrive_folder <id>
"""

import logging
from html import escape
from pathlib import Path
from pyrogram import filters, enums
from pyrogram.types import Message
from downloaders.drive_downloader import DriveDownloader, DriveUploader, take_video_screenshots

logger = logging.getLogger(__name__)

VIDEO_EXTS  = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v'}
AUDIO_EXTS  = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac'}
IMAGE_EXTS  = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


def register(app, user_states, download_dir, default_folder_id=None, sync_dir=None):
    """Registra los handlers de Google Drive y sincronización local.

    Si ``sync_dir`` está definido, /drive_sync guarda allí el siguiente archivo
    sin usar la API de Google Drive. El modo /gdrive_upload conserva la subida
    directa mediante OAuth.
    """

    # ── Descarga desde Drive ──────────────────────────────────────────────────
    @app.on_message(filters.command(['gdrive', 'drive', 'dldrive']))
    async def gdrive_download(client, message: Message):
        """Descarga un archivo de Google Drive dado su URL o ID."""
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text(
                "☁️ <b>Google Drive Downloader</b>\n\n"
                "Envía el enlace o ID del archivo:\n"
                "<code>/gdrive https://drive.google.com/file/d/XXXX/view</code>\n"
                "<code>/gdrive 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        url_or_id = args[1].strip()
        user_id   = message.from_user.id
        user_dir  = download_dir / f"user_{user_id}"
        user_dir.mkdir(exist_ok=True)

        status_msg = await message.reply_text(
            "☁️ <b>Conectando con Google Drive…</b>",
            parse_mode=enums.ParseMode.HTML
        )

        async def tg_progress(text):
            try:
                await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

        success, file_path, error = await DriveDownloader.download(url_or_id, user_dir, tg_progress)

        if not success:
            await status_msg.edit_text(
                f"❌ <b>Error descargando de Drive</b>\n\n{error}",
                parse_mode=enums.ParseMode.HTML
            )
            return

        file_size = file_path.stat().st_size / (1024 * 1024)
        file_ext  = file_path.suffix.lower()
        filename  = file_path.name

        await status_msg.edit_text(
            f"✅ <b>Descarga completada</b>\n📄 {filename}\n📦 {file_size:.1f} MB\n📤 Enviando…",
            parse_mode=enums.ParseMode.HTML
        )

        # Screenshots si es video
        if file_ext in VIDEO_EXTS:
            await _send_screenshots(message, file_path, user_dir, "drive")

        # Enviar archivo
        last_pct = [0]
        async def upload_progress(current, total):
            pct = int(current / total * 100)
            if pct - last_pct[0] >= 10:
                logger.info(f"📤 Telegram upload {pct}%")
                last_pct[0] = pct

        try:
            await _send_file(message, file_path, file_ext, filename, "Drive", upload_progress)
            await status_msg.delete()
        except Exception as e:
            logger.error(f"❌ Error enviando a Telegram: {e}")
            await status_msg.edit_text("❌ Error enviando el archivo a Telegram.")

        file_path.unlink(missing_ok=True)
        logger.info("🗑️ Archivo temporal eliminado")

    # ── Subida directa a Drive mediante API ───────────────────────────────────
    @app.on_message(filters.command(['gdrive_upload', 'drive_upload', 'updrive']))
    async def gdrive_upload_start(client, message: Message):
        """Activa el modo de subida a Drive. El siguiente archivo enviado se subirá."""
        user_id = message.from_user.id
        args    = message.text.split(maxsplit=1)
        folder_id = args[1].strip() if len(args) > 1 else default_folder_id

        user_states[user_id] = {
            'action': 'gdrive_upload',
            'step':   'waiting_file',
            'folder_id': folder_id,
        }

        folder_info = f"\n📁 Carpeta destino: <code>{escape(folder_id)}</code>" if folder_id else "\n📁 Carpeta destino: Mi unidad"
        await message.reply_text(
            f"☁️ <b>Modo Subida a Drive</b>{folder_info}\n\n"
            "Envíame un documento, foto, video o audio para subirlo a Google Drive.",
            parse_mode=enums.ParseMode.HTML
        )

    # ── Copia local para sincronización Android, sin API ──────────────────────
    @app.on_message(filters.command(['drive_sync', 'sync_drive']))
    async def drive_sync_start(client, message: Message):
        """Activa el modo que guarda el siguiente archivo en la carpeta compartida."""
        if sync_dir is None:
            await message.reply_text("❌ La carpeta de sincronización no está configurada.")
            return
        user_id = message.from_user.id
        user_states[user_id] = {
            'action': 'drive_sync',
            'step': 'waiting_file',
        }
        await message.reply_text(
            f"📁 <b>Modo sincronización local</b>\n\n"
            f"Envía el archivo y se guardará en:\n<code>{escape(str(sync_dir))}</code>\n\n"
            "Una aplicación de sincronización podrá copiarlo a Google Drive.",
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.document | filters.photo | filters.video | filters.audio)
    async def gdrive_upload_file(client, message: Message):
        """Recibe el archivo y lo sube a Drive si el estado es gdrive_upload."""
        user_id = message.from_user.id

        if user_id not in user_states:
            return
        state = user_states[user_id]
        action = state.get('action')
        if action not in ('gdrive_upload', 'drive_sync') or state.get('step') != 'waiting_file':
            return

        folder_id = state.get('folder_id')
        user_dir  = download_dir / f"user_{user_id}"
        user_dir.mkdir(exist_ok=True)

        media = message.document or message.photo or message.video or message.audio
        if not media:
            return

        original_name = getattr(media, 'file_name', None)
        if original_name:
            filename = Path(original_name).name
        else:
            suffix = '.jpg' if message.photo else ''
            filename = f"file_{media.file_unique_id}{suffix}"
        filename = filename or f"file_{media.file_unique_id}"
        mime_type = getattr(media, 'mime_type', None) or ('image/jpeg' if message.photo else 'application/octet-stream')

        status_msg = await message.reply_text("⬇️ Descargando archivo de Telegram…")

        try:
            file_path = Path(await message.download(
                file_name=str(user_dir / filename)
            ))

            file_size = file_path.stat().st_size / (1024 * 1024)
            file_ext  = file_path.suffix.lower()
            logger.info(f"✅ Archivo descargado: {file_path.name} ({file_size:.1f} MB)")

            if action == 'drive_sync':
                sync_dir.mkdir(parents=True, exist_ok=True)
                target_path = sync_dir / file_path.name
                file_path.replace(target_path)
                await status_msg.edit_text(
                    f"✅ <b>Archivo guardado en Termux</b>\n"
                    f"📄 {escape(target_path.name)}\n"
                    f"📦 {file_size:.1f} MB\n\n"
                    "La aplicación de sincronización puede subirlo a Google Drive.",
                    parse_mode=enums.ParseMode.HTML,
                )
                del user_states[user_id]
                return

            await status_msg.edit_text(
                f"📤 <b>Subiendo a Drive…</b>\n📄 {escape(file_path.name)}\n📦 {file_size:.1f} MB",
                parse_mode=enums.ParseMode.HTML
            )

            async def tg_progress(text):
                try:
                    await status_msg.edit_text(text, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass

            success, info, error = await DriveUploader.upload(
                file_path,
                folder_id,
                mime_type=mime_type,
                progress_callback=tg_progress,
            )

            if success:
                link = info.get('webViewLink') or (
                    f"https://drive.google.com/file/d/{info['id']}/view"
                    if info.get('id') else 'Enlace no disponible'
                )
                await status_msg.edit_text(
                    f"✅ <b>Subido a Google Drive</b>\n"
                    f"📄 {escape(info.get('name', file_path.name))}\n"
                    f"🔗 {escape(link, quote=True)}",
                    parse_mode=enums.ParseMode.HTML
                )
                logger.info(f"✅ Subida completa: {link}")
            else:
                await status_msg.edit_text(
                    f"❌ <b>Error subiendo a Drive</b>\n{escape(str(error))}",
                    parse_mode=enums.ParseMode.HTML
                )

            file_path.unlink(missing_ok=True)
            del user_states[user_id]

        except Exception as e:
            logger.error(f"❌ Error en subida Drive: {e}", exc_info=True)
            user_states.pop(user_id, None)
            await status_msg.edit_text(f"❌ Error: {escape(str(e)[:200])}", parse_mode=enums.ParseMode.HTML)


# ── Helpers internos ──────────────────────────────────────────────────────────

async def _send_screenshots(message: Message, video_path: Path, work_dir: Path, prefix: str):
    """Captura y envía 5 screenshots del video como álbum de fotos."""
    logger.info("📸 Capturando screenshots del video…")
    shots = await take_video_screenshots(video_path, work_dir, prefix=prefix)

    if not shots:
        logger.warning("⚠️ No se generaron screenshots")
        return

    from pyrogram.types import InputMediaPhoto
    media_group = [InputMediaPhoto(str(s)) for s in shots]
    media_group[0] = InputMediaPhoto(
        str(shots[0]),
        caption="🎬 <b>Preview del video</b>",
    )

    try:
        await message.reply_media_group(media=media_group)
        logger.info(f"✅ {len(shots)} screenshots enviados")
    except Exception as e:
        logger.warning(f"⚠️ Error enviando screenshots: {e}")
    finally:
        for s in shots:
            s.unlink(missing_ok=True)


async def _send_file(message: Message, file_path: Path, file_ext: str, filename: str, service: str, progress):
    """Envía el archivo al chat según su tipo."""
    caption = f"✅ Descargado de {service}\n📄 {filename}"
    if file_ext in VIDEO_EXTS:
        await message.reply_video(video=str(file_path), caption=caption, supports_streaming=True, progress=progress)
    elif file_ext in AUDIO_EXTS:
        await message.reply_audio(audio=str(file_path), caption=caption, progress=progress)
    elif file_ext in IMAGE_EXTS:
        await message.reply_photo(photo=str(file_path), caption=caption, progress=progress)
    else:
        await message.reply_document(document=str(file_path), caption=caption, progress=progress)
