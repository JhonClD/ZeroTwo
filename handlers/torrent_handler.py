"""Handler para enlaces magnet, URLs directas y archivos .torrent."""

import asyncio
import html
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders.torrent_downloader import TorrentDownloader
from utils import VideoProcessor

logger = logging.getLogger(__name__)
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}
_TORRENT_URL_RE = re.compile(r"^https?://\S+\.torrent(?:\?\S*)?$", re.IGNORECASE)


def _progress_bar(pct, width=10):
    pct = max(0, min(100, int(pct)))
    filled = int(width * pct / 100)
    return "■" * filled + "▢" * (width - filled)


def _format_size(size):
    size = max(0, int(size or 0))
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"


def _format_elapsed(seconds):
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _torrent_status_text(metrics):
    name = html.escape(str(metrics.get("name") or "Torrent"))
    completed = int(metrics.get("completed_size") or 0)
    total_size = int(metrics.get("total_size") or 0)
    percent = int(metrics.get("percent") or 0)
    if total_size:
        size_text = f"{_format_size(completed)} / {_format_size(total_size)}"
        percent = max(percent, min(100, int(completed * 100 / total_size)))
    else:
        size_text = f"{_format_size(completed)} / Calculando…"
    current_files = int(metrics.get("current_files") or 0)
    total_files = int(metrics.get("total_files") or 0)
    files_text = f"{current_files} / {total_files}" if total_files else f"{current_files} / Calculando…"
    return (
        "📥 <b>Descargando torrent</b>\n"
        f"┃ <b>Nombre:</b> <code>{name}</code>\n"
        f"┣ <b>Size:</b> {size_text}\n"
        f"┣ <b>Elapsed:</b> {_format_elapsed(metrics.get('elapsed'))}\n"
        f"┣ <b>Progreso:</b> {_progress_bar(percent)} {percent}%\n"
        f"┗ <b>Total Files:</b> {files_text}"
    )


def _is_torrent_url(value):
    if not isinstance(value, str) or not _TORRENT_URL_RE.fullmatch(value.strip()):
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and parsed.path.lower().endswith(".torrent")


async def _send_file(message, path: Path, status: Message, source_label: str):
    size = path.stat().st_size / (1024 * 1024)
    caption = f"✅ Torrent descargado\n📄 {path.name}\n📦 {size:.1f} MB"
    last = [-10]

    async def progress(current, total):
        if not total:
            return
        pct = int(current / total * 100)
        if pct - last[0] < 10 and pct != 100:
            return
        last[0] = pct
        try:
            await status.edit_text(
                f"📤 <b>Enviando {source_label} a Telegram</b>\n{_progress_bar(pct)} {pct}%",
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
    loop = asyncio.get_running_loop()
    status_lock = asyncio.Lock()
    progress_active = [True]
    last_progress_edit = [0.0]

    async def update_progress(metrics):
        if not progress_active[0]:
            return
        async with status_lock:
            if not progress_active[0]:
                return
            try:
                await status.edit_text(_torrent_status_text(metrics), parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

    def progress_callback(metrics):
        now = time.monotonic()
        if now - last_progress_edit[0] < 2 and metrics.get("percent", 0) < 100:
            return
        last_progress_edit[0] = now
        loop.call_soon_threadsafe(lambda: asyncio.create_task(update_progress(metrics)))

    try:
        await status.edit_text(_torrent_status_text({"name": source_label}), parse_mode=enums.ParseMode.HTML)
        ok, files, error = await asyncio.to_thread(
            TorrentDownloader.download, source, job_dir, None, progress_callback
        )
        progress_active[0] = False
        if not ok:
            await status.edit_text(f"❌ <b>Error torrent</b>\n<code>{html.escape(error[:900])}</code>", parse_mode=enums.ParseMode.HTML)
            return
        for index, path in enumerate(files):
            await _send_file(message, path, status, f"archivo {index + 1}/{len(files)}")
        await status.delete()
    except Exception as error:
        logger.error("Error en descarga torrent", exc_info=True)
        await status.edit_text(f"❌ Error enviando torrent\n<code>{html.escape(str(error)[:700])}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def register(app, download_dir: Path):
    @app.on_message(filters.text & filters.regex(r"^magnet:\?"))
    async def magnet(client, message: Message):
        await _run_torrent(message, message.text.strip(), download_dir, "magnet")

    # El handler genérico de enlaces se registra antes que este; el grupo 1 permite
    # que el enlace .torrent también llegue a este manejador.
    @app.on_message(filters.text & filters.regex(r"(?i)^https?://\S+\.torrent(?:\?\S*)?$"), group=1)
    async def torrent_url(client, message: Message):
        source = message.text.strip()
        if not _is_torrent_url(source):
            return
        await _run_torrent(message, source, download_dir, "enlace .torrent")

    @app.on_message(filters.command("torrent"))
    async def torrent_command(client, message: Message):
        reply = message.reply_to_message
        document = reply.document if reply else None
        if document:
            name = getattr(document, "file_name", "") or "torrent.torrent"
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
                if job_dir.exists() and not any(job_dir.iterdir()):
                    job_dir.rmdir()
            return

        parts = (message.text or "").split(maxsplit=1)
        source = parts[1].strip() if len(parts) > 1 else ""
        if not _is_torrent_url(source):
            await message.reply_text(
                "Uso: pega un magnet, pega una URL directa terminada en .torrent, "
                "o responde a un archivo .torrent con /torrent."
            )
            return
        await _run_torrent(message, source, download_dir, "enlace .torrent")
