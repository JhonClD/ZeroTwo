"""
url_handler.py - Manejador de URLs (MEGA / MediaFire / Drive / Drime)
Muestra barra de progreso en Telegram y en terminal durante descarga y envío.
"""

import asyncio
import html
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from downloaders import MediaFireDownloader, MEGADownloader
from downloaders.drime_downloader import DrimeDownloader, DrimeDownloadError
from downloaders.drive_downloader import DriveDownloader, take_video_screenshots
from downloaders.gofile_downloader import GoFileDownloader, GoFileDownloadError
from utils import VideoProcessor

logger = logging.getLogger(__name__)

VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v'}
AUDIO_EXTS = {'.mp3', '.m4a', '.wav', '.ogg', '.flac', '.aac'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)


def _extract_url(text: str | None) -> str | None:
    """Obtiene el enlace del texto aunque venga precedido por `/mf` u otro comando."""
    if not text:
        return None
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip('.,;:)]}')


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return '▓' * filled + '░' * (width - filled)


def register(app, download_dir):
    """Registra el handler de URLs."""
    try:
        max_drime_mb = max(50, min(4096, int(os.getenv("ZERO_TWO_DRIME_MAX_MB", "1800"))))
    except ValueError:
        max_drime_mb = 1800
    try:
        max_gofile_mb = max(50, min(4096, int(os.getenv("ZERO_TWO_GOFILE_MAX_MB", "1800"))))
    except ValueError:
        max_gofile_mb = 1800
    drime_busy_users: set[int] = set()
    drime_busy_lock = asyncio.Lock()
    gofile_busy_users: set[int] = set()
    gofile_busy_lock = asyncio.Lock()
    gofile_selections = {}

    def _file_label(entry):
        name = Path(str(entry.get("name") or "archivo_drime")).name.replace("\x00", "")
        size = int(entry.get("file_size") or 0)
        if size >= 1024 ** 3:
            size_text = f"{size / (1024 ** 3):.2f} GB"
        else:
            size_text = f"{size / (1024 ** 2):.1f} MB"
        return name or "archivo_drime", size, size_text

    async def _download_and_send_drime(
        message: Message, status_msg: Message, share: dict, entry: dict, user_id: int | None = None
    ):
        if user_id is None:
            user_id = message.from_user.id if message.from_user else 0
        filename, expected_size, size_text = _file_label(entry)
        max_bytes = max_drime_mb * 1024 * 1024
        if expected_size and expected_size > max_bytes:
            await status_msg.edit_text(
                f"❌ <b>{html.escape(filename)}</b> supera el límite configurado de {max_drime_mb} MB.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        user_dir = Path(download_dir) / f"user_{user_id}"
        job_dir = user_dir / f"drime_{uuid.uuid4().hex[:10]}"
        try:
            job_dir.mkdir(parents=True, exist_ok=False)
            if expected_size and shutil.disk_usage(job_dir).free < expected_size + 64 * 1024 * 1024:
                raise DrimeDownloadError("No hay suficiente espacio libre en el hosting para este archivo.")

            escaped_name = html.escape(filename)
            await status_msg.edit_text(
                f"☁️ <b>Descargando desde Drime</b>\n{escaped_name}\n📦 {size_text}\n0%",
                parse_mode=enums.ParseMode.HTML,
            )
            loop = asyncio.get_running_loop()
            last_download_pct = [-10]

            def download_progress(current, total):
                if not total:
                    return
                pct = min(100, int(current * 100 / total))
                if pct - last_download_pct[0] < 10 and pct != 100:
                    return
                last_download_pct[0] = pct

                async def update_status():
                    try:
                        await status_msg.edit_text(
                            f"☁️ <b>Descargando desde Drime</b>\n{escaped_name}\n📦 {size_text}\n{_progress_bar(pct)} {pct}%",
                            parse_mode=enums.ParseMode.HTML,
                        )
                    except Exception:
                        pass

                future = asyncio.run_coroutine_threadsafe(update_status(), loop)
                try:
                    future.result(timeout=20)
                except Exception:
                    pass

            destination = job_dir / filename
            file_path, file_size_bytes = await asyncio.to_thread(
                DrimeDownloader.download_file,
                share["share_hash"], share["share_id"], entry, destination, max_bytes, download_progress,
            )
            file_size = file_size_bytes / (1024 * 1024)
            await status_msg.edit_text(
                f"✅ <b>Descarga de Drime completada</b>\n{escaped_name}\n"
                f"📦 {file_size:.1f} MB\n📤 Enviando a Telegram…",
                parse_mode=enums.ParseMode.HTML,
            )
            last_upload_pct = [-10]

            async def upload_progress(current, total):
                if not total:
                    return
                pct = min(100, int(current * 100 / total))
                if pct - last_upload_pct[0] < 10 and pct != 100:
                    return
                last_upload_pct[0] = pct
                try:
                    await status_msg.edit_text(
                        f"📤 <b>Enviando desde Drime a Telegram</b>\n{escaped_name}\n"
                        f"{_progress_bar(pct)} {pct}%",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

            await message.reply_document(
                document=str(file_path),
                caption=f"✅ Descargado de Drime\n📄 {filename}\n📦 {file_size:.1f} MB",
                progress=upload_progress,
            )
            await status_msg.delete()
        except DrimeDownloadError as error:
            await status_msg.edit_text(f"❌ <b>Error de Drime</b>\n{html.escape(str(error))}", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            logger.exception("Error descargando o enviando archivo de Drime")
            try:
                await status_msg.edit_text(
                    f"❌ Error al descargar/enviar desde Drime\n<code>{html.escape(str(error)[:500])}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        finally:
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)

    def _gofile_file_label(entry):
        name = GoFileDownloader._safe_filename(entry.get("name"), str(entry.get("id") or "file"))
        try:
            size = max(0, int(entry.get("size") or 0))
        except (TypeError, ValueError):
            size = 0
        if size >= 1024 ** 3:
            size_text = f"{size / (1024 ** 3):.2f} GB"
        elif size:
            size_text = f"{size / (1024 ** 2):.1f} MB"
        else:
            size_text = "tamaño desconocido"
        return name, size, size_text

    async def _download_and_send_gofile(message, status_msg, share, entry, user_id=None):
        if user_id is None:
            user_id = message.from_user.id if message.from_user else 0
        filename, expected_size, size_text = _gofile_file_label(entry)
        max_bytes = max_gofile_mb * 1024 * 1024
        if expected_size and expected_size > max_bytes:
            await status_msg.edit_text(
                f"❌ <b>{html.escape(filename)}</b> supera el límite de {max_gofile_mb} MB configurado para GoFile.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        user_dir = Path(download_dir) / f"user_{user_id}"
        job_dir = user_dir / f"gofile_{uuid.uuid4().hex[:10]}"
        try:
            job_dir.mkdir(parents=True, exist_ok=False)
            if expected_size and shutil.disk_usage(job_dir).free < expected_size + 64 * 1024 * 1024:
                raise GoFileDownloadError("No hay suficiente espacio libre en el hosting para este archivo.")

            escaped_name = html.escape(filename)
            await status_msg.edit_text(
                f"☁️ <b>Descargando desde GoFile</b>\n{escaped_name}\n📦 {size_text}\n0%",
                parse_mode=enums.ParseMode.HTML,
            )
            loop = asyncio.get_running_loop()
            last_download_pct = [-10]

            def download_progress(current, total):
                if not total:
                    return
                pct = min(100, int(current * 100 / total))
                if pct - last_download_pct[0] < 10 and pct != 100:
                    return
                last_download_pct[0] = pct

                async def update_status():
                    try:
                        await status_msg.edit_text(
                            f"☁️ <b>Descargando desde GoFile</b>\n{escaped_name}\n📦 {size_text}\n"
                            f"{_progress_bar(pct)} {pct}%",
                            parse_mode=enums.ParseMode.HTML,
                        )
                    except Exception:
                        pass

                future = asyncio.run_coroutine_threadsafe(update_status(), loop)
                try:
                    future.result(timeout=20)
                except Exception:
                    pass

            destination = job_dir / filename
            file_path, downloaded_bytes = await asyncio.to_thread(
                GoFileDownloader.download_file,
                entry,
                destination,
                max_bytes,
                download_progress,
                share.get("content_id", ""),
            )
            file_size = downloaded_bytes / (1024 * 1024)
            await status_msg.edit_text(
                f"✅ <b>Descarga de GoFile completada</b>\n{escaped_name}\n"
                f"📦 {file_size:.1f} MB\n📤 Enviando a Telegram…",
                parse_mode=enums.ParseMode.HTML,
            )
            last_upload_pct = [-10]

            async def upload_progress(current, total):
                if not total:
                    return
                pct = min(100, int(current * 100 / total))
                if pct - last_upload_pct[0] < 10 and pct != 100:
                    return
                last_upload_pct[0] = pct
                try:
                    await status_msg.edit_text(
                        f"📤 <b>Enviando desde GoFile a Telegram</b>\n{escaped_name}\n"
                        f"{_progress_bar(pct)} {pct}%",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

            await message.reply_document(
                document=str(file_path),
                caption=f"✅ Descargado de GoFile\n📄 {filename}\n📦 {file_size:.1f} MB",
                progress=upload_progress,
            )
            await status_msg.delete()
        except GoFileDownloadError as error:
            await status_msg.edit_text(
                f"❌ <b>Error de GoFile</b>\n{html.escape(str(error))}",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as error:
            logger.exception("Error descargando o enviando archivo de GoFile")
            try:
                await status_msg.edit_text(
                    f"❌ Error al descargar/enviar desde GoFile\n<code>{html.escape(str(error)[:500])}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        finally:
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)

    @app.on_message(filters.text & filters.regex(r'https?://'))
    async def handle_url(client, message: Message):
        url = _extract_url(message.text)
        if not url:
            return
        user_id  = message.from_user.id
        username = message.from_user.username or message.from_user.first_name

        logger.info(f"🔗 URL de @{username}: {url[:80]}")

        is_mega      = MEGADownloader.is_mega_url(url)
        is_mediafire = MediaFireDownloader.is_mediafire_url(url)
        is_drive     = DriveDownloader.is_drive_url(url)
        is_drime     = DrimeDownloader.is_drime_url(url)
        is_gofile    = GoFileDownloader.is_gofile_url(url)

        if not any([is_mega, is_mediafire, is_drive, is_drime, is_gofile]):
            logger.info("⏭️ URL ignorada (no es un servicio de descarga compatible)")
            return

        if is_mega:
            service = "MEGA"
        elif is_mediafire:
            service = "MediaFire"
        elif is_drime:
            service = "Drime"
        elif is_gofile:
            service = "GoFile"
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
            if is_gofile:
                share = await asyncio.to_thread(GoFileDownloader.list_shared_files, url)
                entries = share["files"]
                if len(entries) == 1:
                    async with gofile_busy_lock:
                        if user_id in gofile_busy_users:
                            await status_msg.edit_text("Ya tienes una descarga GoFile en curso.")
                            return
                        gofile_busy_users.add(user_id)
                    try:
                        await _download_and_send_gofile(message, status_msg, share, entries[0])
                    finally:
                        async with gofile_busy_lock:
                            gofile_busy_users.discard(user_id)
                    return

                buttons = []
                for entry in entries[:30]:
                    filename, _, size_text = _gofile_file_label(entry)
                    label = f"📥 {filename} ({size_text})"
                    if len(label) > 64:
                        label = label[:61] + "…"
                    if len(gofile_selections) >= 500:
                        gofile_selections.pop(next(iter(gofile_selections)))
                    selector_id = uuid.uuid4().hex[:12]
                    gofile_selections[selector_id] = {
                        "user_id": user_id,
                        "share": share,
                        "entry": entry,
                    }
                    callback_data = f"gf:{user_id}:{selector_id}"
                    buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
                if not buttons:
                    raise GoFileDownloadError("No pude crear el selector para los archivos de esta carpeta.")
                count = "100 o más" if share.get("truncated") else str(len(entries))
                more = "\nSolo se muestran los primeros 30 archivos." if len(entries) > 30 or share.get("truncated") else ""
                await status_msg.edit_text(
                    f"📂 <b>Carpeta pública de GoFile</b>\nEncontré {count} archivos. "
                    f"Elige cuál quieres descargar:{more}",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
                return

            if is_drime:
                share = await asyncio.to_thread(DrimeDownloader.list_shared_files, url)
                entries = share["files"]
                if len(entries) == 1:
                    async with drime_busy_lock:
                        if user_id in drime_busy_users:
                            await status_msg.edit_text("Ya tienes una descarga Drime en curso.")
                            return
                        drime_busy_users.add(user_id)
                    try:
                        await _download_and_send_drime(message, status_msg, share, entries[0])
                    finally:
                        async with drime_busy_lock:
                            drime_busy_users.discard(user_id)
                    return

                buttons = []
                for entry in entries[:30]:
                    filename, _, size_text = _file_label(entry)
                    label = f"📥 {filename} ({size_text})"
                    if len(label) > 64:
                        label = label[:61] + "…"
                    callback_data = f"d:{user_id}:{share['share_hash']}:{entry['hash']}"
                    if len(callback_data.encode("utf-8")) <= 64:
                        buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
                if not buttons:
                    raise DrimeDownloadError("No pude crear botones de selección para los archivos de esta carpeta.")
                more = "\nSolo se muestran los primeros 30 archivos." if len(entries) > 30 else ""
                await status_msg.edit_text(
                    f"📂 <b>Carpeta pública de Drime</b>\nEncontré {len(entries)} archivos. "
                    f"Elige cuál quieres descargar:{more}",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
                return
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

            # Screenshots si es video
            if file_ext in VIDEO_EXTS:
                await _send_screenshots(message, file_path, user_dir, service.lower().replace(' ', '_'))

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
                    thumb_path = user_dir / f"{file_path.stem}_thumb.jpg"
                    duration, thumb = VideoProcessor.get_video_meta(file_path, thumb_path)
                    await message.reply_video(
                        video=str(file_path), caption=caption,
                        supports_streaming=True, progress=send_progress,
                        duration=duration or None, thumb=thumb,
                    )
                    thumb_path.unlink(missing_ok=True)
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

        except GoFileDownloadError as e:
            logger.warning("Error en enlace GoFile: %s", e)
            await status_msg.edit_text(
                f"❌ <b>Error de GoFile</b>\n{html.escape(str(e))}",
                parse_mode=enums.ParseMode.HTML,
            )
        except DrimeDownloadError as e:
            logger.warning("Error en enlace Drime: %s", e)
            await status_msg.edit_text(
                f"❌ <b>Error de Drime</b>\n{html.escape(str(e))}",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"❌ Error en handle_url: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ <b>Error</b>\n{str(e)[:200]}",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_callback_query(filters.regex(r"^d:\d+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$"))
    async def drime_download_callback(client, query):
        parts = (query.data or "").split(":", 3)
        if len(parts) != 4 or query.message is None:
            await query.answer("Este botón de descarga no es válido.", show_alert=True)
            return
        _, owner_id, share_hash, entry_hash = parts
        try:
            owner_id = int(owner_id)
        except ValueError:
            await query.answer("Este botón de descarga no es válido.", show_alert=True)
            return
        if not query.from_user or query.from_user.id != owner_id:
            await query.answer("Este selector pertenece a otra persona.", show_alert=True)
            return

        async with drime_busy_lock:
            if owner_id in drime_busy_users:
                await query.answer("Ya tienes una descarga Drime en curso.", show_alert=True)
                return
            drime_busy_users.add(owner_id)
        await query.answer("Preparando descarga…")
        try:
            share_url = f"https://app.drime.cloud/drive/s/{share_hash}"
            share = await asyncio.to_thread(DrimeDownloader.list_shared_files, share_url)
            entry = next((item for item in share["files"] if item.get("hash") == entry_hash), None)
            if entry is None:
                await query.message.edit_text("❌ El archivo ya no aparece en esta carpeta compartida.")
                return
            await _download_and_send_drime(query.message, query.message, share, entry, user_id=owner_id)
        except DrimeDownloadError as error:
            await query.message.edit_text(f"❌ <b>Error de Drime</b>\n{html.escape(str(error))}", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            logger.exception("Error procesando selección Drime")
            try:
                await query.message.edit_text(f"❌ Error procesando Drime: {html.escape(str(error)[:400])}")
            except Exception:
                pass
        finally:
            async with drime_busy_lock:
                drime_busy_users.discard(owner_id)

    @app.on_callback_query(filters.regex(r"^gf:\d+:[a-f0-9]{12}$"))
    async def gofile_download_callback(client, query):
        parts = (query.data or "").split(":", 2)
        if len(parts) != 3 or query.message is None:
            await query.answer("Este botón de descarga no es válido.", show_alert=True)
            return
        _, owner_id, selector_id = parts
        try:
            owner_id = int(owner_id)
        except ValueError:
            await query.answer("Este botón de descarga no es válido.", show_alert=True)
            return
        if not query.from_user or query.from_user.id != owner_id:
            await query.answer("Este selector pertenece a otra persona.", show_alert=True)
            return

        selection = gofile_selections.get(selector_id)
        if not selection or selection.get("user_id") != owner_id:
            await query.answer("Este selector venció. Vuelve a enviar el enlace.", show_alert=True)
            return
        async with gofile_busy_lock:
            if owner_id in gofile_busy_users:
                await query.answer("Ya tienes una descarga GoFile en curso.", show_alert=True)
                return
            gofile_busy_users.add(owner_id)
            selection = gofile_selections.pop(selector_id, None)
        if not selection:
            async with gofile_busy_lock:
                gofile_busy_users.discard(owner_id)
            await query.answer("Este selector venció. Vuelve a enviar el enlace.", show_alert=True)
            return

        await query.answer("Preparando descarga…")
        try:
            await _download_and_send_gofile(
                query.message,
                query.message,
                selection["share"],
                selection["entry"],
                user_id=owner_id,
            )
        except Exception as error:
            logger.exception("Error procesando selección GoFile")
            try:
                await query.message.edit_text(f"❌ Error procesando GoFile: {html.escape(str(error)[:400])}")
            except Exception:
                pass
        finally:
            async with gofile_busy_lock:
                gofile_busy_users.discard(owner_id)


# ── Helper de screenshots ──────────────────────────────────────────────────────

async def _send_screenshots(message: Message, video_path: Path, work_dir: Path, prefix: str):
    """Captura 5 screenshots y los envía como álbum."""
    logger.info("📸 Capturando screenshots del video…")
    shots = await take_video_screenshots(video_path, work_dir, prefix=prefix)
    if not shots:
        return

    from pyrogram.types import InputMediaPhoto
    media_group = [InputMediaPhoto(str(s)) for s in shots]
    media_group[0] = InputMediaPhoto(str(shots[0]), caption="🎬 <b>Preview del video</b>")

    try:
        await message.reply_media_group(media=media_group)
        logger.info(f"✅ {len(shots)} screenshots enviados")
    except Exception as e:
        logger.warning(f"⚠️ Error enviando screenshots: {e}")
    finally:
        for s in shots:
            s.unlink(missing_ok=True)
