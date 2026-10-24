"""Integración opcional con el ejecutable externo aniDL para Crunchyroll."""
from __future__ import annotations

import asyncio
import html
import logging
import os
from pathlib import Path
import shutil
import time
import uuid

from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from utils.anidl import (
    AniDLError,
    build_command,
    changed_videos,
    extract_episode_id,
    parse_options,
    snapshot_videos,
)
from utils.transfer_status import TransferProgress, render_transfer_status

logger = logging.getLogger(__name__)
ANIDL_OWNER_ID = 7856571519


def _is_anidl_owner(message: Message) -> bool:
    """Solo la cuenta configurada por el propietario puede iniciar AniDL."""
    return bool(message.from_user and message.from_user.id == ANIDL_OWNER_ID)


def _ani_dl_setup() -> tuple[Path, Path, str, int, int] | tuple[None, None, None, int, int]:
    """Resuelve la instalación local sin leer ni solicitar credenciales."""
    work_dir = Path(os.getenv("ZERO_TWO_ANIDL_DIR", str(Path.home() / "anidl"))).expanduser()
    try:
        work_dir = work_dir.resolve(strict=True)
    except OSError:
        return None, None, None, _positive_env("ZERO_TWO_ANIDL_TIMEOUT", 10800), _positive_env("ZERO_TWO_ANIDL_MAX_MB", 1900)
    if not work_dir.is_dir():
        return None, None, None, _positive_env("ZERO_TWO_ANIDL_TIMEOUT", 10800), _positive_env("ZERO_TWO_ANIDL_MAX_MB", 1900)

    configured = os.getenv("ZERO_TWO_ANIDL_BIN", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute() and ("/" in configured or "\\" in configured):
            candidate = work_dir / candidate
        executable = str(candidate.resolve()) if candidate.exists() else shutil.which(configured)
    else:
        local_binary = work_dir / "aniDL"
        executable = str(local_binary) if local_binary.is_file() else shutil.which("aniDL")
    if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        return None, None, None, _positive_env("ZERO_TWO_ANIDL_TIMEOUT", 10800), _positive_env("ZERO_TWO_ANIDL_MAX_MB", 1900)

    output_dir = work_dir / "videos"
    return (
        work_dir,
        output_dir,
        executable,
        _positive_env("ZERO_TWO_ANIDL_TIMEOUT", 10800),
        _positive_env("ZERO_TWO_ANIDL_MAX_MB", 1900),
    )


def _positive_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Valor inválido en %s; se usará el predeterminado.", name)
        return default


def register(app, download_dir: Path | str | None = None) -> None:
    """Registra /ani y /anidl, con botón de cancelación por usuario."""
    del download_dir  # AniDL administra su salida en <ZERO_TWO_ANIDL_DIR>/videos.
    run_lock = asyncio.Lock()
    jobs: dict[str, dict] = {}
    owner_jobs: dict[int, str] = {}

    def _cancel_markup(job_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancelar descarga", callback_data=f"anidl:cancel:{job_id}"),
        ]])

    @app.on_message(filters.command(["ani", "anidl"]))
    async def anidl_command(client, message: Message):
        if not _is_anidl_owner(message):
            await message.reply_text("⛔ Solo el propietario puede usar AniDL.")
            return

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text(
                "🎌 <b>AniDL · Crunchyroll</b>\n\n"
                "Uso: <code>/ani URL [--dubLang jpn] [--dlsubs all|none|CODIGO] "
                "[-q 1..5] [--mp4|--mkv]</code>\n"
                "Predeterminados: audio japonés, softsubs todos, calidad 4 y MP4. "
                "Requiere AniDL instalado y configurado localmente en el hosting.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        pieces = args[1].split(maxsplit=1)
        url = pieces[0]
        option_text = pieces[1] if len(pieces) > 1 else ""
        try:
            episode_id = extract_episode_id(url)
            options = parse_options(option_text)
        except AniDLError as error:
            await message.reply_text(f"❌ {html.escape(str(error))}", parse_mode=enums.ParseMode.HTML)
            return

        work_dir, output_dir, executable, timeout_seconds, max_mb = _ani_dl_setup()
        if not work_dir or not output_dir or not executable:
            await message.reply_text(
                "❌ AniDL no está listo. Instala el ejecutable <code>aniDL</code> y su configuración local; "
                "por defecto ZeroTwo busca la instalación en <code>~/anidl</code>.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        owner_id = message.from_user.id
        if owner_id in owner_jobs:
            await message.reply_text("Ya tienes una descarga AniDL activa.")
            return

        status = await message.reply_text("⏳ <b>Preparando descarga AniDL…</b>", parse_mode=enums.ParseMode.HTML)
        try:
            await asyncio.wait_for(run_lock.acquire(), timeout=0.05)
        except asyncio.TimeoutError:
            await status.edit_text("⏳ AniDL está ocupado con otra descarga. Inténtalo de nuevo cuando termine.")
            return

        job_id = uuid.uuid4().hex[:10]
        job = {"owner_id": owner_id, "process": None, "cancelled": False}
        jobs[job_id] = job
        owner_jobs[owner_id] = job_id
        started = time.monotonic()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            before = snapshot_videos(output_dir)
            argv = build_command(executable, episode_id, options)
            job["status"] = status
            await status.edit_text(
                "📥 <b>Descargando episodio con AniDL…</b>\n"
                f"ID: <code>{html.escape(episode_id)}</code> · audio {html.escape(options.dub_language)} · "
                f"softsubs {html.escape(options.download_subtitles)} · calidad {options.quality} · "
                f"{options.container.upper()}\n"
                "La salida se conserva en el directorio de AniDL.",
                reply_markup=_cancel_markup(job_id),
                parse_mode=enums.ParseMode.HTML,
            )
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(work_dir),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            job["process"] = process
            if job["cancelled"]:
                process.terminate()

            while process.returncode is None:
                elapsed = time.monotonic() - started
                if elapsed >= timeout_seconds:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                    await status.edit_text(
                        f"⏱️ AniDL excedió el límite de {timeout_seconds} segundos. Los archivos existentes se conservaron."
                    )
                    return
                try:
                    await asyncio.wait_for(process.wait(), timeout=min(12, timeout_seconds - elapsed))
                except asyncio.TimeoutError:
                    if not job["cancelled"]:
                        try:
                            await status.edit_text(
                                "📥 <b>AniDL sigue descargando…</b>\n"
                                f"ID: <code>{html.escape(episode_id)}</code> · {int(elapsed)} s",
                                reply_markup=_cancel_markup(job_id),
                                parse_mode=enums.ParseMode.HTML,
                            )
                        except Exception:
                            pass

            if job["cancelled"]:
                await status.edit_text("🚫 Descarga cancelada. Los archivos preexistentes no se borraron.")
                return
            if process.returncode != 0:
                logger.warning("AniDL terminó con código %s para el episodio solicitado.", process.returncode)
                await status.edit_text(
                    "❌ AniDL no pudo completar la descarga. Revisa la instalación, la disponibilidad del episodio "
                    "y la sesión local de AniDL; el detalle del proceso no se publica en Telegram."
                )
                return

            videos = changed_videos(output_dir, before)
            if not videos:
                await status.edit_text(
                    "⚠️ AniDL terminó sin errores, pero no encontré videos nuevos o modificados en "
                    "<code>~/anidl/videos</code>. Comprueba la carpeta de salida.",
                    parse_mode=enums.ParseMode.HTML,
                )
                return

            sent = 0
            for path in videos:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > max_mb * 1024 * 1024:
                    await status.edit_text(
                        f"⚠️ <code>{html.escape(path.name)}</code> supera el límite configurado de {max_mb} MB. "
                        "El archivo se conserva en el hosting.",
                        parse_mode=enums.ParseMode.HTML,
                    )
                    continue
                await status.edit_text(
                    f"📤 Enviando <code>{html.escape(path.name)}</code> a Telegram…",
                    parse_mode=enums.ParseMode.HTML,
                )
                tracker = TransferProgress()
                last_update = [0.0]

                async def upload_progress(current: int, total: int, *_):
                    now = time.monotonic()
                    if current < total and now - last_update[0] < 4:
                        return
                    last_update[0] = now
                    text = render_transfer_status(
                        "Enviando", "Telegram", path.name, current, total, tracker,
                    )
                    try:
                        await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
                    except Exception:
                        pass

                caption = f"🎌 AniDL · Crunchyroll\n{path.name[:700]}"
                if path.suffix.lower() == ".mp4":
                    await message.reply_video(
                        video=str(path),
                        caption=caption,
                        supports_streaming=True,
                        progress=upload_progress,
                    )
                else:
                    await message.reply_document(
                        document=str(path),
                        caption=caption,
                        progress=upload_progress,
                    )
                sent += 1

            await status.edit_text(
                f"✅ AniDL finalizó. Envié {sent} archivo(s); la salida permanece en "
                "<code>~/anidl/videos</code> para que puedas conservarla o limpiarla manualmente.",
                parse_mode=enums.ParseMode.HTML,
            )
        except asyncio.CancelledError:
            process = job.get("process")
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise
        except Exception:
            logger.exception("Error en integración AniDL")
            try:
                await status.edit_text("❌ Ocurrió un error al ejecutar AniDL o enviar el archivo. Los archivos se conservaron.")
            except Exception:
                pass
        finally:
            jobs.pop(job_id, None)
            owner_jobs.pop(owner_id, None)
            run_lock.release()

    @app.on_callback_query(filters.regex(r"^anidl:cancel:[a-f0-9]{10}$"))
    async def cancel_anidl(client, query):
        job_id = query.data.rsplit(":", 1)[-1]
        job = jobs.get(job_id)
        if not job or not query.from_user or query.from_user.id != job["owner_id"]:
            await query.answer("Esta descarga no te pertenece o ya terminó.", show_alert=True)
            return
        job["cancelled"] = True
        process = job.get("process")
        if process and process.returncode is None:
            process.terminate()
        await query.answer("Cancelando descarga…")
