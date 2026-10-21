"""Handler para enlaces magnet y archivos .torrent."""

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders.torrent_downloader import TorrentDownloader
from utils import VideoProcessor
from utils.transfer_status import TransferProgress, format_file_info, render_transfer_status

logger = logging.getLogger(__name__)
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}


async def _send_file(message, path: Path, status: Message, source_label: str):
    size = path.stat().st_size / (1024 * 1024)
    caption = f"✅ Torrent descargado\n📄 {path.name}\n📦 {size:.1f} MB"
    last = [-10]
    meter = TransferProgress()
    await status.edit_text(
        f"✅ <b>Descarga torrent completada</b>\n{format_file_info(path, 'Torrent')}\n"
        f"📤 Preparando envío · {source_label}",
        parse_mode=enums.ParseMode.HTML,
    )

    async def progress(current, total):
        if not total:
            return
        pct = int(current / total * 100)
        if pct - last[0] < 10 and pct != 100:
            return
        last[0] = pct
        try:
            await status.edit_text(
                render_transfer_status(
                    "Subiendo", "Telegram · Torrent", path.name,
                    current, total, meter, source_label,
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass

    if path.suffix.lower() in _VIDEO_EXTS:
        thumb = path.with_suffix(".jpg")
        duration, thumb_path = await asyncio.to_thread(VideoProcessor.get_video_meta, path, thumb)
        await message.reply_video(video=str(path), thumb=thumb_path, caption=caption,
                                  duration=duration or None, supports_streaming=True, progress=progress)
        thumb.unlink(missing_ok=True)
    else:
        await message.reply_document(document=str(path), caption=caption, progress=progress)


async def _run_torrent(message: Message, source, download_dir: Path, source_label="torrent"):
    job_dir = download_dir / f"torrent_{message.from_user.id}_{uuid.uuid4().hex[:8]}"
    status = await message.reply_text("⏳ Preparando descarga torrent…")
    try:
        meter = TransferProgress()
        last_pct = [-10]
        loop = asyncio.get_running_loop()
        await status.edit_text(
            render_transfer_status(
                "Descargando", "Torrent / aria2", "Preparando metadatos",
                0, 0, meter, source_label,
            ),
            parse_mode=enums.ParseMode.HTML,
        )

        def torrent_progress(current, total, speed=None):
            if total:
                pct = min(100, int(current * 100 / total))
                if pct - last_pct[0] < 10 and pct != 100:
                    return
                last_pct[0] = pct

            async def update_status():
                try:
                    await status.edit_text(
                        render_transfer_status(
                            "Descargando", "Torrent / aria2", "Descarga torrent",
                            current, total, meter, source_label, speed_override=speed,
                        ),
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

            future = asyncio.run_coroutine_threadsafe(update_status(), loop)
            try:
                future.result(timeout=20)
            except Exception:
                pass

        ok, files, error = await asyncio.to_thread(
            TorrentDownloader.download, source, job_dir, progress_callback=torrent_progress,
        )
        if not ok:
            await status.edit_text(f"❌ <b>Error torrent</b>\n<code>{error[:900]}</code>", parse_mode=enums.ParseMode.HTML)
            return
        for index, path in enumerate(files):
            await _send_file(message, path, status, f"archivo {index + 1}/{len(files)}")
        await status.delete()
    except Exception as error:
        logger.error("Error en descarga torrent", exc_info=True)
        await status.edit_text(f"❌ Error enviando torrent\n<code>{str(error)[:700]}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def register(app, download_dir: Path):
    @app.on_message(filters.text & filters.regex(r"^magnet:\?"))
    async def magnet(client, message: Message):
        await _run_torrent(message, message.text.strip(), download_dir, "magnet")

    @app.on_message(filters.command("torrent") & filters.reply)
    async def torrent_file(client, message: Message):
        reply = message.reply_to_message
        document = reply.document if reply else None
        name = getattr(document, "file_name", "") if document else ""
        if not name.lower().endswith(".torrent"):
            await message.reply_text("❌ Responde a un archivo .torrent con /torrent.")
            return
        job_dir = download_dir / f"torrent_source_{message.from_user.id}_{uuid.uuid4().hex[:8]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        source = job_dir / Path(name).name
        try:
            await reply.download(file_name=str(source))
            await _run_torrent(message, source, download_dir, name)
        finally:
            source.unlink(missing_ok=True)
            job_dir.rmdir() if job_dir.exists() and not any(job_dir.iterdir()) else None
