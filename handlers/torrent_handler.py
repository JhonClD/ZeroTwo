"""Handler para enlaces magnet y archivos .torrent."""

import asyncio
import logging
import shutil
import time
import uuid
from html import escape
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders.torrent_downloader import TorrentDownloader
from utils import VideoProcessor
from utils.download_queue import download_queue
from utils.transfer_status import TransferProgress, format_bytes, format_file_info, format_duration, render_transfer_status

logger = logging.getLogger(__name__)
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}


async def _send_file(message, path: Path, status: Message, source_label: str, torrent_context=None):
    size = path.stat().st_size / (1024 * 1024)
    caption = f"✅ Torrent descargado\n📄 {path.name}\n📦 {size:.1f} MB"
    last = [-10]
    meter = TransferProgress()
    if torrent_context:
        await status.edit_text(
            _torrent_status(
                path.name, path.stat().st_size, path.stat().st_size,
                "Preparando envío", torrent_context["queue_position"], 0,
                (torrent_context["seeds"], torrent_context["peers"]),
                torrent_context["started_at"], torrent_context["task_id"],
                show_peers=False,
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    else:
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
            if torrent_context:
                text = _torrent_status(
                    path.name, current, total, "Enviando a Telegram",
                    torrent_context["queue_position"], None,
                    (torrent_context["seeds"], torrent_context["peers"]),
                    torrent_context["started_at"], torrent_context["task_id"], meter,
                    show_peers=False,
                )
            else:
                text = render_transfer_status(
                    "Subiendo", "Telegram · Torrent", path.name,
                    current, total, meter, source_label,
                )
            await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
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
    task_id = uuid.uuid4().hex[:4].upper()
    started_at = time.monotonic()
    torrent_name = Path(str(source)).stem if not str(source).startswith("magnet:") else "Torrent"
    status = await message.reply_text(
        _torrent_status(torrent_name, 0, 0, "En cola", 1, 0, None, started_at, task_id)
    )
    try:
        meter = TransferProgress()
        last_update = [0.0]
        last_stats = [None, None]
        loop = asyncio.get_running_loop()
        queue_position = 1 + download_queue.pending

        def torrent_progress(current, total, speed=None, seeds=None, peer_count=None):
            last_stats[:] = [seeds, peer_count]
            now = time.monotonic()
            if now - last_update[0] < 1.5 and total and current < total:
                return
            last_update[0] = now

            async def update_status():
                try:
                    await status.edit_text(
                        _torrent_status(torrent_name, current, total, "Descargando", queue_position,
                                        speed, (seeds, peer_count), started_at, task_id, meter),
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

            future = asyncio.run_coroutine_threadsafe(update_status(), loop)
            try:
                future.result(timeout=20)
            except Exception:
                pass

        async def queued_notice(position):
            await status.edit_text(
                _torrent_status(torrent_name, 0, 0, "En cola", position, None, None,
                                started_at, task_id),
                parse_mode=enums.ParseMode.HTML,
            )

        async def download_job():
            return await asyncio.to_thread(
                TorrentDownloader.download, source, job_dir, progress_callback=torrent_progress,
            )

        ok, files, error = await download_queue.run(
            "Torrent", download_job, on_queued=queued_notice,
        )
        if not ok:
            await status.edit_text(f"❌ <b>Error torrent</b>\n<code>{error[:900]}</code>", parse_mode=enums.ParseMode.HTML)
            return
        for index, path in enumerate(files):
            await _send_file(
                message, path, status, f"archivo {index + 1}/{len(files)}",
                torrent_context={
                    "queue_position": queue_position,
                    "seeds": last_stats[0],
                    "peers": last_stats[1],
                    "started_at": started_at,
                    "task_id": task_id,
                },
            )
        await status.delete()
    except Exception as error:
        logger.error("Error en descarga torrent", exc_info=True)
        await status.edit_text(f"❌ Error enviando torrent\n<code>{str(error)[:700]}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def _torrent_status(name, current, total, stage, queue_position, speed, peers,
                    started_at, task_id, meter=None, show_peers=True):
    """Renderiza el formato compacto de progreso solicitado para torrents."""
    meter = meter or TransferProgress()
    snapshot = meter.snapshot(current, total)
    percent = snapshot["percent"] or 0
    filled = min(13, int(13 * percent / 100))
    bar = "■" * filled + "□" * (13 - filled)
    speed_bytes = speed if speed is not None else snapshot["speed"]
    speed_text = f"↓ {(speed_bytes or 0) / (1024 ** 2):.2f} MiB/s"
    eta = ((total - current) / speed_bytes if speed_bytes and total else None)
    elapsed = max(0, int(time.monotonic() - started_at))
    size_text = f"{format_bytes(current)} / {format_bytes(total)}"
    lines = [
        f"<b>{escape(Path(str(name or 'Torrent')).name)}</b>\n"
        f"┃ [{bar}] {percent:05.2f}%\n"
        f"┠ Size: {size_text}\n"
        f"┠ Status: {escape(stage)}...\n"
        f"┠ Queue: posición {queue_position}\n"
        f"┠ Speed: {speed_text} | ETA: {format_duration(eta)}\n"
    ]
    if show_peers:
        seeds = peers[0] if isinstance(peers, tuple) else "—"
        peer_count = peers[1] if isinstance(peers, tuple) else "—"
        lines.append(f"┠ Seeds: {seeds} | Peers: {peer_count}\n")
    lines.extend([
        f"┠ Elapsed: {elapsed // 60}m {elapsed % 60:02d}s\n"
        f"┠ Mode: #Download | #Torrent\n"
        f"┗ Cancelar: /cancel {task_id}"
    ])
    return "".join(lines)


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
