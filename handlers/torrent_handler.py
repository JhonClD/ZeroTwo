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
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from downloaders.torrent_downloader import TorrentDownloader
from utils import VideoProcessor

logger = logging.getLogger(__name__)
_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}
_TORRENT_URL_RE = re.compile(r"^https?://\S+\.torrent(?:\?\S*)?$", re.IGNORECASE)
_PENDING_TORRENT_SELECTIONS = {}
_SELECTION_PAGE_SIZE = 8


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


def _selection_view(selection_id, state):
    entries = state["entries"]
    page = state["page"]
    page_count = max(1, (len(entries) + _SELECTION_PAGE_SIZE - 1) // _SELECTION_PAGE_SIZE)
    page = max(0, min(page, page_count - 1))
    state["page"] = page
    start = page * _SELECTION_PAGE_SIZE
    visible = entries[start:start + _SELECTION_PAGE_SIZE]
    rows = []
    for entry in visible:
        index = entry["index"]
        chosen = index in state["selected"]
        filename = Path(entry["name"]).name or entry["name"]
        if len(filename) > 42:
            filename = filename[:39] + "…"
        label = f"{'☑' if chosen else '☐'} {index:02d} · {filename}"
        rows.append([InlineKeyboardButton(label, callback_data=f"tr:{selection_id}:t:{index}")])

    selected_count = len(state["selected"])
    rows.append([InlineKeyboardButton(
        f"⬇️ Descargar seleccionados ({selected_count})",
        callback_data=f"tr:{selection_id}:go",
    )])
    rows.append([
        InlineKeyboardButton("Seleccionar todos", callback_data=f"tr:{selection_id}:all"),
        InlineKeyboardButton("Limpiar", callback_data=f"tr:{selection_id}:clear"),
    ])
    if page_count > 1:
        rows.append([
            InlineKeyboardButton("◀️ Anterior", callback_data=f"tr:{selection_id}:p:{max(0, page - 1)}"),
            InlineKeyboardButton(f"{page + 1}/{page_count}", callback_data=f"tr:{selection_id}:p:{page}"),
            InlineKeyboardButton("Siguiente ▶️", callback_data=f"tr:{selection_id}:p:{min(page_count - 1, page + 1)}"),
        ])
    rows.append([InlineKeyboardButton("Cancelar", callback_data=f"tr:{selection_id}:cancel")])

    title = html.escape(str(state.get("name") or "Torrent"))
    text = (
        f"📂 <b>{title}</b>\n"
        f"Este torrent contiene <b>{len(entries)}</b> archivos. Marca los capítulos que quieres descargar.\n"
        f"Página {page + 1}/{page_count} · Seleccionados: <b>{selected_count}</b>"
    )
    return text, InlineKeyboardMarkup(rows)


async def _download_torrent_selection(message, status, state, selected_indices):
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
        await status.edit_text(
            f"✅ Selección: <b>{len(selected_indices)}</b> archivo(s)\nPreparando descarga…",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
        ok, files, error = await asyncio.to_thread(
            TorrentDownloader.download,
            state["source"], state["job_dir"], None, progress_callback,
            selected_indices, state["metainfo_path"],
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
        progress_active[0] = False
        shutil.rmtree(state["job_dir"], ignore_errors=True)


async def _run_torrent(message: Message, source, download_dir: Path, source_label="torrent"):
    job_dir = download_dir / f"torrent_{message.from_user.id}_{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    # Copia los .torrent subidos a la carpeta de trabajo; el handler de entrada
    # puede borrar su archivo temporal al volver de esta función.
    if isinstance(source, Path):
        staged_source = job_dir / "uploaded.torrent"
        shutil.copy2(source, staged_source)
        source = staged_source
    status = await message.reply_text("⏳ Leyendo archivos del torrent…")
    keep_job_dir = False
    try:
        ok, prepared_source, metainfo_path, entries, error = await asyncio.to_thread(
            TorrentDownloader.prepare_selection, source, job_dir
        )
        if not ok:
            await status.edit_text(f"❌ <b>Error torrent</b>\n<code>{html.escape(error[:900])}</code>", parse_mode=enums.ParseMode.HTML)
            return
        metadata = await asyncio.to_thread(TorrentDownloader._torrent_metadata, metainfo_path)
        if len(entries) > 1:
            selection_id = uuid.uuid4().hex[:10]
            state = {
                "owner_id": message.from_user.id,
                "source": prepared_source,
                "metainfo_path": metainfo_path,
                "entries": entries,
                "selected": set(),
                "page": 0,
                "name": metadata.get("name") or source_label,
                "job_dir": job_dir,
                "source_message": message,
            }
            if len(_PENDING_TORRENT_SELECTIONS) >= 100:
                oldest = next(iter(_PENDING_TORRENT_SELECTIONS))
                expired = _PENDING_TORRENT_SELECTIONS.pop(oldest)
                shutil.rmtree(expired["job_dir"], ignore_errors=True)
            _PENDING_TORRENT_SELECTIONS[selection_id] = state
            text, keyboard = _selection_view(selection_id, state)
            await status.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
            keep_job_dir = True
            return

        state = {
            "source": prepared_source,
            "metainfo_path": metainfo_path,
            "job_dir": job_dir,
        }
        await _download_torrent_selection(message, status, state, [entries[0]["index"]])
    except Exception as error:
        logger.error("Error preparando torrent", exc_info=True)
        try:
            await status.edit_text(
                f"❌ Error preparando torrent\n<code>{html.escape(str(error)[:700])}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
    finally:
        if not keep_job_dir:
            shutil.rmtree(job_dir, ignore_errors=True)


def register(app, download_dir: Path):
    @app.on_callback_query(filters.regex(r"^tr:[a-f0-9]{10}:(?:t:\d+|p:\d+|all|clear|go|cancel)$"))
    async def torrent_selection_callback(client, query):
        parts = query.data.split(":")
        selection_id = parts[1]
        action = parts[2]
        state = _PENDING_TORRENT_SELECTIONS.get(selection_id)
        if not state:
            await query.answer("Este selector venció. Envía el torrent otra vez.", show_alert=True)
            return
        if not query.from_user or query.from_user.id != state["owner_id"]:
            await query.answer("Este selector pertenece a otra persona.", show_alert=True)
            return

        if action == "t":
            index = int(parts[3])
            if index not in {entry["index"] for entry in state["entries"]}:
                await query.answer("Ese archivo no está en el torrent.", show_alert=True)
                return
            if index in state["selected"]:
                state["selected"].remove(index)
            else:
                state["selected"].add(index)
        elif action == "p":
            state["page"] = int(parts[3])
        elif action == "all":
            state["selected"] = {entry["index"] for entry in state["entries"]}
        elif action == "clear":
            state["selected"].clear()
        elif action == "cancel":
            _PENDING_TORRENT_SELECTIONS.pop(selection_id, None)
            await query.answer("Selección cancelada.")
            await query.message.edit_text("❎ Selección torrent cancelada.")
            await asyncio.to_thread(shutil.rmtree, state["job_dir"], ignore_errors=True)
            return
        elif action == "go":
            selected = sorted(state["selected"])
            if not selected:
                await query.answer("Marca al menos un capítulo para continuar.", show_alert=True)
                return
            if state.get("busy"):
                await query.answer("La descarga ya está iniciándose.")
                return
            state["busy"] = True
            _PENDING_TORRENT_SELECTIONS.pop(selection_id, None)
            await query.answer("Iniciando descarga de los archivos elegidos…")
            await _download_torrent_selection(state["source_message"], query.message, state, selected)
            return

        text, keyboard = _selection_view(selection_id, state)
        await query.answer()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

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
