"""Flujos nuevos de compresión y quemado de subtítulos para videos."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from utils import VideoProcessor
from utils.video_processing import (
    VideoProcessingError,
    build_compression_commands,
    build_hardsub_template_commands,
    build_target_size_commands,
    calculate_video_bitrate,
    compression_profile,
    has_subtitles_filter,
    probe_video,
    run_ffmpeg,
    safe_video_extension,
)

logger = logging.getLogger(__name__)


def _progress_bar(percent: float, width: int = 12) -> str:
    percent = max(0, min(100, percent))
    full = round(width * percent / 100)
    return "■" * full + "□" * (width - full)


def _duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def _elapsed_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m {seconds % 60}s"


def _template_status(
    *,
    video_name: str,
    percent: float,
    status: str,
    elapsed: float,
    user_mention: str,
    user_id: int,
    info: str = "Encode | -c:v libx264 -vb plantilla",
    mode: str = "#Leech | #Pyrogram",
    processed: str | None = None,
    cancel_text: str = "cancel_en_espera",
) -> str:
    processed_line = f"<b>┠ Processed:</b> {processed}\n" if processed else ""
    return (
        f"<b>{html.escape(video_name)}</b>\n"
        f"┃ [{_progress_bar(percent, 13)}] {max(0, min(100, percent)):05.2f}%\n"
        f"{processed_line}"
        f"<b>┠ Status:</b> {html.escape(status)}\n"
        f"<b>┠ Speed:</b> 0.00 MiB/s <b>| Elapsed:</b> {_elapsed_text(elapsed)}\n"
        f"<b>┠ Info:</b> {html.escape(info)}\n"
        f"<b>┠ Mode:</b> {html.escape(mode)}\n"
        f"<b>┠ User:</b> {html.escape(user_mention)} <b>| ID:</b> <code>{user_id}</code>\n"
        f"<b>┖</b><code> {html.escape(cancel_text)}</code>"
    )


def register(app, user_states: dict, work_dir: Path) -> None:
    """Registra handlers del flujo; user_states se conserva por compatibilidad de app."""
    del user_states
    root = Path(work_dir) / "video_processing"
    root.mkdir(parents=True, exist_ok=True)
    flows: dict[str, dict] = {}
    user_flow: dict[int, str] = {}
    admitting_users: set[int] = set()
    admission_lock = asyncio.Lock()
    scheduled: set[str] = set()
    def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
        except (TypeError, ValueError):
            logger.warning("Valor inválido en %s; se usará %s.", name, default)
            return default

    worker_count = _env_int("ZERO_TWO_VIDEO_WORKERS", 1, 1, 2)
    max_queue = _env_int("ZERO_TWO_VIDEO_QUEUE", 2, 1, 6)
    max_input_mb = _env_int("ZERO_TWO_VIDEO_MAX_MB", 1800, 100, 4096)
    threads = _env_int("ZERO_TWO_FFMPEG_THREADS", 2, 1, 8)
    timeout = _env_int("ZERO_TWO_FFMPEG_TIMEOUT", 7200, 60, 21600)
    slots = asyncio.Semaphore(worker_count)
    preparation_slot = asyncio.Semaphore(1)

    def _owner_id(message: Message) -> int:
        return message.from_user.id if message.from_user else message.chat.id

    def _cancel_markup(job_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancelar proceso", callback_data=f"vp:cancel:{job_id}"),
        ]])

    async def _download_progress(current: int, total: int, status: Message, timer: list[float], job_id: str, state: dict):
        now = time.monotonic()
        if now - timer[0] < 3 and current < total:
            return
        timer[0] = now
        percent = current * 100 / total if total else 0
        user = state["request"].from_user
        user_mention = f"@{user.username}" if user and user.username else (user.first_name if user else "Desconocido")
        user_id = user.id if user else state["owner_id"]
        text = _template_status(
            video_name=state["display_name"], percent=percent, status="Downloading",
            elapsed=time.monotonic() - state["started_at"], user_mention=user_mention, user_id=user_id,
            info="Download | Telegram", mode="#Leech | #Pyrogram",
            processed=f"{current / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MiB",
        )
        try:
            await status.edit_text(text, reply_markup=_cancel_markup(job_id), parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    def _action_markup(job_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Comprimir", callback_data=f"vp:action:{job_id}:compress")],
            [InlineKeyboardButton("Quemar subtítulos", callback_data=f"vp:action:{job_id}:subtitles")],
            [InlineKeyboardButton("Cancelar", callback_data=f"vp:cancel:{job_id}")],
        ])

    def _compression_markup(job_id: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Equilibrado", callback_data=f"vp:crf:{job_id}:balanced"),
             InlineKeyboardButton("Menor tamaño", callback_data=f"vp:crf:{job_id}:smaller")],
            [InlineKeyboardButton("Mejor calidad", callback_data=f"vp:crf:{job_id}:quality")],
            [InlineKeyboardButton("Reducir a 720p", callback_data=f"vp:crf:{job_id}:720"),
             InlineKeyboardButton("Reducir a 480p", callback_data=f"vp:crf:{job_id}:480")],
            [InlineKeyboardButton("Cancelar", callback_data=f"vp:cancel:{job_id}")],
        ])

    async def _show_subtitle_options(job_id: str) -> None:
        state = flows[job_id]
        tracks = state["media"]["subtitles"]
        rows = [
            [InlineKeyboardButton(
                f"Pista {track['ordinal'] + 1}: {track['label']}"[:62],
                callback_data=f"vp:sub:{job_id}:{track['ordinal']}",
            )]
            for track in tracks[:12]
        ]
        rows.append([InlineKeyboardButton("Usar archivo .srt/.ass/.vtt", callback_data=f"vp:external:{job_id}")])
        rows.append([InlineKeyboardButton("Cancelar", callback_data=f"vp:cancel:{job_id}")])
        message = "📝 <b>Elige la pista de subtítulos para quemar</b>"
        if not tracks:
            message = "📝 <b>El video no contiene pistas de texto.</b> Envía un archivo .srt, .ass o .vtt."
        await state["status"].edit_text(
            message,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        state["stage"] = "subtitle_options"

    async def _show_audio_options(job_id: str) -> None:
        state = flows[job_id]
        tracks = state["media"].get("audio", [])
        rows = [
            [InlineKeyboardButton(
                f"Pista {track['ordinal'] + 1}: {track['label']}"[:62],
                callback_data=f"vp:audio:{job_id}:{track['ordinal']}",
            )]
            for track in tracks[:12]
        ]
        rows.append([InlineKeyboardButton("Continuar sin audio", callback_data=f"vp:audio:{job_id}:none")])
        rows.append([InlineKeyboardButton("Cancelar", callback_data=f"vp:cancel:{job_id}")])
        message = "🎧 <b>Elige la pista de audio que conservar</b>"
        if not tracks:
            message = "🎧 <b>El video no contiene pistas de audio.</b> Puedes continuar sin audio."
        await state["status"].edit_text(
            message,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        state["stage"] = "audio_options"

    async def _prepare(message: Message, flow_kind: str, target_size: float | None = None) -> None:
        owner_id = _owner_id(message)
        async with admission_lock:
            if owner_id in user_flow or owner_id in admitting_users:
                await message.reply_text("Ya tienes un proceso de video abierto. Termínalo o cancélalo antes de iniciar otro.")
                return
            if len(user_flow) + len(admitting_users) >= max_queue + worker_count:
                await message.reply_text("El bot ya tiene el máximo de sesiones de video abiertas. Inténtalo más tarde.")
                return
            admitting_users.add(owner_id)
        source_message = message.reply_to_message
        media = (source_message.video or source_message.document) if source_message else None
        if not media or (
            source_message.document
            and not str(getattr(media, "mime_type", "")).startswith("video/")
            and Path(getattr(media, "file_name", "")).suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
        ):
            admitting_users.discard(owner_id)
            await message.reply_text(
                "Responde a un video o documento de video con /process, /compress o /subtitles.\n"
                "Puedes usar /compress 700 para intentar ajustarlo aproximadamente a 700 MB."
            )
            return

        reported_size = int(getattr(media, "file_size", 0) or 0)
        if reported_size > max_input_mb * 1024 * 1024:
            admitting_users.discard(owner_id)
            await message.reply_text(f"El video supera el límite de procesamiento de {max_input_mb} MB configurado en este hosting.")
            return
        try:
            initial_name = getattr(media, "file_name", None) or "video"
            user = message.from_user
            user_mention = f"@{user.username}" if user and user.username else (user.first_name if user else "Desconocido")
            status = await message.reply_text(
                _template_status(video_name=initial_name, percent=0, status="En cola…", elapsed=0,
                                 user_mention=user_mention, user_id=owner_id),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            admitting_users.discard(owner_id)
            raise
        extension = safe_video_extension(getattr(media, "file_name", ""), getattr(media, "mime_type", None))
        try:
            job_dir = Path(tempfile.mkdtemp(prefix=f"job_{owner_id}_", dir=root))
        except OSError as error:
            admitting_users.discard(owner_id)
            await status.edit_text(f"No se pudo crear el directorio temporal: <code>{html.escape(str(error)[:250])}</code>", parse_mode=enums.ParseMode.HTML)
            return
        job_id = uuid.uuid4().hex[:8]
        source = job_dir / f"input{extension}"
        state = {
            "job_id": job_id,
            "owner_id": owner_id,
            "request": message,
            "source_message": source_message,
            "status": status,
            "job_dir": job_dir,
            "source": source,
            "flow_kind": flow_kind,
            "target_size": target_size,
            "stage": "downloading",
            "media": None,
            "task": None,
            "prepare_task": asyncio.current_task(),
            "external_task": None,
            "display_name": getattr(media, "file_name", None) or f"video{extension}",
            "started_at": time.monotonic(),
        }
        flows[job_id] = state
        admitting_users.discard(owner_id)
        user_flow[owner_id] = job_id
        try:
            await status.edit_text(
                _template_status(video_name=state["display_name"], percent=0, status="Downloading", elapsed=0,
                                 user_mention=user_mention, user_id=owner_id, info="Download | Telegram"),
                reply_markup=_cancel_markup(job_id), parse_mode=enums.ParseMode.HTML,
            )
            async with preparation_slot:
                reserved_outputs = sum(
                    flow["source"].stat().st_size
                    for flow in flows.values()
                    if flow["job_id"] != job_id and flow["source"].exists()
                )
                estimated_space = reported_size * 2 + reserved_outputs + 128 * 1024 * 1024
                if reported_size and shutil.disk_usage(root).free < estimated_space:
                    raise VideoProcessingError("No hay espacio temporal suficiente. Libera espacio en el hosting e inténtalo de nuevo.")
                timer = [0.0]
                await source_message.download(
                    file_name=str(source),
                    progress=_download_progress,
                    progress_args=(status, timer, job_id, state),
                )
                if not source.exists() or source.stat().st_size == 0:
                    raise VideoProcessingError("Telegram no entregó un archivo de video válido.")
                if source.stat().st_size > max_input_mb * 1024 * 1024:
                    raise VideoProcessingError(f"El video descargado supera el máximo de {max_input_mb} MB.")
                media_info = await probe_video(source)
            state["media"] = media_info
            state["prepare_task"] = None
            if flow_kind == "process":
                state["stage"] = "action_options"
                await status.edit_text(
                    "🎞 <b>Video listo.</b> ¿Qué quieres hacer?",
                    reply_markup=_action_markup(job_id),
                    parse_mode=enums.ParseMode.HTML,
                )
            elif flow_kind == "compress":
                if target_size is not None:
                    input_size_mb = source.stat().st_size / (1024 * 1024)
                    if target_size >= input_size_mb:
                        raise VideoProcessingError(
                            f"El video original ya pesa {input_size_mb:.1f} MB; el objetivo debe ser menor. Usa /compress sin tamaño para elegir un perfil."
                        )
                    enqueued = await _enqueue(job_id, "size", target_size=target_size)
                    if not enqueued:
                        state["stage"] = "compression_options"
                        await status.edit_text(
                            "La cola está llena. Puedes elegir un perfil de una pasada o cancelar y probar más tarde.",
                            reply_markup=_compression_markup(job_id),
                        )
                else:
                    state["stage"] = "compression_options"
                    await status.edit_text(
                        "📦 <b>Elige el perfil de compresión</b>\n"
                        "Equilibrado y menor tamaño usan una sola pasada. El tamaño objetivo usa dos pasadas y tarda más.",
                        reply_markup=_compression_markup(job_id),
                        parse_mode=enums.ParseMode.HTML,
                    )
            else:
                can_burn = await has_subtitles_filter()
                if not can_burn:
                    raise VideoProcessingError("Este FFmpeg no incluye el filtro subtitles/libass. En el panel se necesita una build de FFmpeg con libass.")
                await _show_subtitle_options(job_id)
        except asyncio.CancelledError:
            await _finish(job_id)
            raise
        except Exception as error:
            logger.exception("No se pudo preparar el trabajo de video")
            try:
                await status.edit_text(f"❌ No se pudo preparar el video.\n<code>{html.escape(str(error)[:700])}</code>", parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass
            await _finish(job_id)

    async def _enqueue(job_id: str, mode: str, **options) -> bool:
        state = flows.get(job_id)
        if not state:
            return False
        if len(scheduled) >= max_queue:
            await state["status"].edit_text(
                f"La cola está llena ({max_queue} trabajos). Cancela un trabajo pendiente o inténtalo más tarde.",
                reply_markup=_cancel_markup(job_id),
            )
            return False
        state["stage"] = "queued"
        state["mode"] = mode
        state.update(options)
        scheduled.add(job_id)
        state["task"] = asyncio.create_task(_run_job(job_id), name=f"video-{job_id}")
        return True

    async def _progress(state: dict, current: float, total: float, stage: str) -> None:
        percent = current * 100 / total if total > 0 else 0
        elapsed = time.monotonic() - state["started_at"]
        user = state["request"].from_user
        user_mention = f"@{user.username}" if user and user.username else (user.first_name if user else "Desconocido")
        user_id = user.id if user else state["owner_id"]
        text = _template_status(
            video_name=state["display_name"], percent=percent, status=stage, elapsed=elapsed,
            user_mention=user_mention, user_id=user_id,
        )
        try:
            await state["status"].edit_text(text, reply_markup=_cancel_markup(state["job_id"]), parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    async def _run_job(job_id: str) -> None:
        state = flows.get(job_id)
        if not state:
            scheduled.discard(job_id)
            return
        try:
            async with slots:
                if state["mode"] == "size":
                    duration = float(state["media"]["duration"])
                    bitrate = calculate_video_bitrate(state["target_size"], duration)
                    output = state["job_dir"] / "compressed.mp4"
                    commands, temporary_files = build_target_size_commands(
                        state["source"].name, output.name, bitrate=bitrate, threads=threads,
                    )
                    await _progress(state, 0, duration, f"En cola · objetivo {state['target_size']:g} MB")
                    total_steps = len(commands)
                    for step, command in enumerate(commands, start=1):
                        async def size_progress(current, total, step=step):
                            await _progress(state, (step - 1) * total + current, total * total_steps, f"Encodeo · paso {step}/{total_steps}")
                        await run_ffmpeg(command, cwd=state["job_dir"], duration=duration, progress_callback=size_progress, timeout_seconds=timeout)
                    for temporary_file in temporary_files:
                        (state["job_dir"] / temporary_file).unlink(missing_ok=True)
                    caption = f"✅ Compresión completada · objetivo aproximado {state['target_size']:g} MB"
                elif state["mode"] == "compress":
                    bitrate, preset, scale = compression_profile(state["profile"])
                    output = state["job_dir"] / "compressed.mp4"
                    commands, temporary_files = build_compression_commands(
                        state["source"].name, output.name, bitrate=bitrate, preset=preset, scale=scale, threads=threads,
                    )
                    await _progress(state, 0, state["media"]["duration"], "En cola · encodeo")
                    total_steps = len(commands)
                    for step, command in enumerate(commands, start=1):
                        async def compression_progress(current, total, step=step):
                            await _progress(state, (step - 1) * total + current, total * total_steps, f"Encodeo · paso {step}/{total_steps}")
                        await run_ffmpeg(command, cwd=state["job_dir"], duration=state["media"]["duration"], progress_callback=compression_progress, timeout_seconds=timeout)
                    for temporary_file in temporary_files:
                        (state["job_dir"] / temporary_file).unlink(missing_ok=True)
                    caption = f"✅ Video comprimido · perfil {state['profile']}"
                else:
                    output = state["job_dir"] / "subtitled.mp4"
                    commands, temporary_files = build_hardsub_template_commands(
                        state["source"].name,
                        output.name,
                        subtitle_name=state.get("external_subtitle"),
                        embedded_ordinal=state.get("subtitle_ordinal"),
                        audio_ordinal=state["audio_ordinal"],
                        bitrate=os.getenv("ZERO_TWO_HARDSUB_BITRATE", "4800k"),
                        preset=os.getenv("ZERO_TWO_HARDSUB_PRESET", "medium"),
                        threads=threads,
                    )
                    await _progress(state, 0, state["media"]["duration"], "En cola · subtítulos y encodeo")
                    total_steps = len(commands)
                    for step, command in enumerate(commands, start=1):
                        async def template_progress(current, total, step=step):
                            await _progress(
                                state, (step - 1) * total + current, total * total_steps,
                                f"Encodeo · paso {step}/{total_steps}",
                            )
                        await run_ffmpeg(
                            command,
                            cwd=state["job_dir"],
                            duration=state["media"]["duration"],
                            progress_callback=template_progress,
                            timeout_seconds=timeout,
                        )
                    for temporary_file in temporary_files:
                        (state["job_dir"] / temporary_file).unlink(missing_ok=True)
                    caption = "✅ Encodeo y subtítulos quemados"

                if not output.exists() or output.stat().st_size == 0:
                    raise VideoProcessingError("FFmpeg no generó un archivo de salida.")
                if output.stat().st_size > 1950 * 1024 * 1024:
                    raise VideoProcessingError("El resultado supera 1950 MB y no se enviará por Telegram.")
                thumb = state["job_dir"] / "thumb.jpg"
                _, thumbnail = await asyncio.to_thread(VideoProcessor.get_video_meta, output, thumb)
                size_mb = output.stat().st_size / (1024 * 1024)
                caption += f"\n📦 {size_mb:.1f} MB"
                await _progress(state, 100, state["media"]["duration"], "Encodeo completado · enviando video")
                await state["request"].reply_video(
                    video=str(output),
                    thumb=thumbnail,
                    caption=caption,
                    duration=int(state["media"]["duration"]) or None,
                    supports_streaming=True,
                )
                try:
                    user = state["request"].from_user
                    user_mention = f"@{user.username}" if user and user.username else (user.first_name if user else "Desconocido")
                    user_id = user.id if user else state["owner_id"]
                    await state["status"].edit_text(
                        _template_status(
                            video_name=state["display_name"], percent=100, status="Completado · video enviado",
                            elapsed=time.monotonic() - state["started_at"], user_mention=user_mention, user_id=user_id,
                            info=f"Encode finalizado · {size_mb:.1f} MiB", cancel_text="proceso_finalizado",
                        ), parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
        except asyncio.CancelledError:
            logger.info("Trabajo de video cancelado: %s", job_id)
            state = flows.get(job_id)
            if state:
                try:
                    await state["status"].edit_text("⛔ Proceso cancelado; se limpiaron los temporales.")
                except Exception:
                    pass
        except Exception as error:
            logger.exception("Error en trabajo de video %s", job_id)
            state = flows.get(job_id)
            if state:
                try:
                    await state["status"].edit_text(
                        f"❌ <b>Falló el procesamiento</b>\n<code>{html.escape(str(error)[:1100])}</code>",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
        finally:
            scheduled.discard(job_id)
            await _finish(job_id)

    async def _finish(job_id: str) -> None:
        state = flows.pop(job_id, None)
        if not state:
            return
        owner_id = state["owner_id"]
        if user_flow.get(owner_id) == job_id:
            user_flow.pop(owner_id, None)
        try:
            await asyncio.to_thread(shutil.rmtree, state["job_dir"], ignore_errors=True)
        except Exception:
            logger.warning("No se pudo limpiar el directorio temporal de %s", job_id, exc_info=True)

    async def _callback(client, query):
        parts = (query.data or "").split(":")
        if len(parts) < 3:
            return await query.answer("Acción inválida.", show_alert=True)
        action, job_id = parts[1], parts[2]
        state = flows.get(job_id)
        if not state:
            return await query.answer("Esta sesión ya expiró.", show_alert=True)
        if state["owner_id"] != query.from_user.id:
            return await query.answer("Este menú pertenece a otra persona.", show_alert=True)
        try:
            if action == "cancel":
                await query.answer("Cancelando…")
                task = state.get("task") or state.get("external_task") or state.get("prepare_task")
                if task and not task.done():
                    task.cancel()
                else:
                    await _finish(job_id)
                    await query.message.edit_text("⛔ Proceso cancelado y archivos temporales eliminados.")
                return
            if state["stage"] in {"queued", "running"}:
                return await query.answer("Este trabajo ya está en cola o ejecutándose.", show_alert=True)

            if action == "action" and len(parts) == 4:
                await query.answer()
                if parts[3] == "compress":
                    state["stage"] = "compression_options"
                    await state["status"].edit_text(
                        "📦 <b>Elige el perfil de compresión</b>",
                        reply_markup=_compression_markup(job_id), parse_mode=enums.ParseMode.HTML,
                    )
                elif parts[3] == "subtitles":
                    if not await has_subtitles_filter():
                        raise VideoProcessingError("Este FFmpeg no incluye subtitles/libass.")
                    await _show_subtitle_options(job_id)
                else:
                    return await query.answer("Acción desconocida.", show_alert=True)
                return

            if action == "crf" and len(parts) == 4:
                enqueued = await _enqueue(job_id, "compress", profile=parts[3])
                await query.answer("Trabajo enviado a la cola" if enqueued else "La cola está llena.", show_alert=not enqueued)
                return

            if action == "sub" and len(parts) == 4:
                ordinal = int(parts[3])
                allowed = {track["ordinal"] for track in state["media"]["subtitles"]}
                if ordinal not in allowed:
                    return await query.answer("La pista seleccionada no existe.", show_alert=True)
                state["subtitle_ordinal"] = ordinal
                await query.answer()
                await _show_audio_options(job_id)
                return

            if action == "audio" and len(parts) == 4:
                if parts[3] == "none":
                    state["audio_ordinal"] = -1
                else:
                    ordinal = int(parts[3])
                    allowed = {track["ordinal"] for track in state["media"].get("audio", [])}
                    if ordinal not in allowed:
                        return await query.answer("La pista de audio seleccionada no existe.", show_alert=True)
                    state["audio_ordinal"] = ordinal
                enqueued = await _enqueue(job_id, "subtitles")
                await query.answer("Encodeo enviado a la cola" if enqueued else "La cola está llena.", show_alert=not enqueued)
                return

            if action == "external":
                state["stage"] = "waiting_external"
                await query.answer()
                await state["status"].edit_text(
                    "📎 <b>Envía ahora el subtítulo externo</b> (.srt, .ass, .ssa o .vtt).\n"
                    "El archivo debe pesar menos de 10 MB.",
                    reply_markup=_cancel_markup(job_id), parse_mode=enums.ParseMode.HTML,
                )
                return
            return await query.answer("Acción desconocida.", show_alert=True)
        except (ValueError, VideoProcessingError) as error:
            await query.answer(str(error)[:180], show_alert=True)
        except Exception as error:
            logger.exception("Error al procesar botón de video")
            await query.answer(f"No se pudo aplicar la opción: {str(error)[:120]}", show_alert=True)

    @app.on_message(filters.command(["process", "video_process"]))
    async def process_command(client, message: Message):
        await _prepare(message, "process")

    @app.on_message(filters.command("compress"))
    async def compress_command(client, message: Message):
        target_size = None
        if len(message.command) > 1:
            try:
                target_size = float(message.command[1])
            except ValueError:
                await message.reply_text("Uso: responde al video con /compress o /compress 700 (tamaño aproximado en MB).")
                return
            if not 40 <= target_size <= 1900:
                await message.reply_text("El tamaño objetivo debe estar entre 40 y 1900 MB.")
                return
        await _prepare(message, "compress", target_size=target_size)

    @app.on_message(filters.command(["subtitles", "sub"]))
    async def subtitles_command(client, message: Message):
        await _prepare(message, "subtitles")

    @app.on_message(filters.command("processstatus"))
    async def process_status_command(client, message: Message):
        owner_id = _owner_id(message)
        job_id = user_flow.get(owner_id)
        state = flows.get(job_id) if job_id else None
        if not state:
            await message.reply_text("No tienes procesos de video pendientes ni activos.")
            return
        stage_labels = {
            "downloading": "descargando y analizando",
            "action_options": "esperando que elijas una acción",
            "compression_options": "esperando el perfil de compresión",
            "subtitle_options": "esperando la pista de subtítulos",
            "audio_options": "esperando la pista de audio",
            "waiting_external": "esperando el archivo de subtítulos",
            "queued": "en cola o en proceso",
        }
        await message.reply_text(f"Trabajo <code>{job_id}</code>: {stage_labels.get(state['stage'], state['stage'])}.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("cancelprocess"))
    async def cancel_process_command(client, message: Message):
        owner_id = _owner_id(message)
        job_id = user_flow.get(owner_id)
        state = flows.get(job_id) if job_id else None
        if not state:
            await message.reply_text("No tienes un proceso de video que cancelar.")
            return
        task = state.get("task") or state.get("external_task") or state.get("prepare_task")
        if task and not task.done():
            task.cancel()
        else:
            await _finish(job_id)
            await message.reply_text("Proceso cancelado y archivos temporales eliminados.")

    @app.on_callback_query(filters.regex(r"^vp:"))
    async def video_callback(client, query):
        await _callback(client, query)

    @app.on_message(filters.document, group=-3)
    async def external_subtitle(client, message: Message):
        owner_id = _owner_id(message)
        job_id = user_flow.get(owner_id)
        state = flows.get(job_id) if job_id else None
        if not state or state.get("stage") != "waiting_external":
            return
        filename = getattr(message.document, "file_name", "") or ""
        suffix = Path(filename).suffix.lower()
        if suffix not in {".srt", ".ass", ".ssa", ".vtt"}:
            await message.reply_text("Ese formato no es compatible. Envía .srt, .ass, .ssa o .vtt.")
            return
        file_size = int(getattr(message.document, "file_size", 0) or 0)
        if file_size > 10 * 1024 * 1024:
            await message.reply_text("El subtítulo supera el límite de 10 MB.")
            return
        subtitle_path = state["job_dir"] / f"subtitle{suffix}"
        state["external_task"] = asyncio.current_task()
        try:
            await message.download(file_name=str(subtitle_path))
            if not subtitle_path.exists() or not subtitle_path.stat().st_size:
                raise VideoProcessingError("Telegram no entregó un subtítulo válido.")
            if subtitle_path.stat().st_size > 10 * 1024 * 1024:
                raise VideoProcessingError("El subtítulo supera el límite de 10 MB.")
            state["external_subtitle"] = subtitle_path.name
            state["external_task"] = None
            await _show_audio_options(job_id)
        except asyncio.CancelledError:
            try:
                await state["status"].edit_text("⛔ Proceso cancelado; se limpiaron los temporales.")
            except Exception:
                pass
            await _finish(job_id)
            raise
        except Exception as error:
            state["external_task"] = None
            logger.exception("No se pudo recibir el archivo de subtítulos")
            await message.reply_text(f"No se pudo usar ese archivo: <code>{html.escape(str(error)[:350])}</code>", parse_mode=enums.ParseMode.HTML)
