"""Flujo guiado para seleccionar, traducir y quemar subtítulos."""

import asyncio
import html
import logging
import os
import shutil
import uuid
from pathlib import Path

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.subtitle_tools import (
    ALIGNMENTS, FONTS, LANGUAGES, alignment_label,
    language_label, safe_filename, translate_subtitle_file, translation_configured,
)
from utils.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt"}


def _user_id(message):
    return message.from_user.id if message.from_user else message.chat.id


def _media_name(message):
    media = message.video or message.document
    return getattr(media, "file_name", "video.mkv") if media else "video.mkv"


def _cleanup(state):
    folder = Path(state["job_dir"])
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def _settings(state):
    return state.setdefault("settings", {"crf": "23", "preset": "veryfast", "alignment": "bottom", "font": "default", "translated": False, "language": "es"})


def _config_keyboard(user_id, state):
    s = _settings(state)
    rows = [
        [InlineKeyboardButton(f"📝 Pista: {state.get('track_label', 'externa')}", callback_data=f"submenu:track:{user_id}")],
        [InlineKeyboardButton(f"↕️ Alineación: {alignment_label(s['alignment'])}", callback_data=f"submenu:align:{user_id}")],
        [InlineKeyboardButton(f"⚡ Preset: {s['preset']}", callback_data=f"submenu:preset:{user_id}")],
        [InlineKeyboardButton(f"🔠 Fuente: {FONTS.get(s['font'], FONTS['dejavu'])[0]}", callback_data=f"submenu:font:{user_id}"), InlineKeyboardButton("✦ Marca: Jap Anime TX", callback_data=f"watermark_info:{user_id}")],
        [InlineKeyboardButton(f"🎚 CRF: {s['crf']}", callback_data=f"submenu:crf:{user_id}"), InlineKeyboardButton("📊 Bitrate: automático", callback_data=f"submenu:bitrate:{user_id}")],
    ]
    if translation_configured() and state.get("external_subtitle"):
        label = f"🌐 Traducir: {language_label(s['language'])}" if s.get("translated") else "🌐 Traducir subtítulos"
        rows.append([InlineKeyboardButton(label, callback_data=f"submenu:translate:{user_id}")])
    rows.append([InlineKeyboardButton("✅ Quemar subtítulos", callback_data=f"sub_start:{user_id}"), InlineKeyboardButton("❌ Cancelar", callback_data=f"sub_cancel:{user_id}")])
    return InlineKeyboardMarkup(rows)


async def _show_config(message, state, title="Configura el procesamiento"):
    target = state.get("status") or message
    await target.edit_text(title + "\nAjusta las opciones y pulsa <b>Quemar subtítulos</b>.", reply_markup=_config_keyboard(state["user_id"], state), parse_mode=enums.ParseMode.HTML)


async def _burn(message, state):
    s = _settings(state)
    video = Path(state["video_path"])
    subtitle = Path(state["external_subtitle"]) if state.get("external_subtitle") else None
    output = Path(state["job_dir"]) / f"{video.stem}_ZeroTwo.mp4"
    status = state["status"]
    try:
        await status.edit_text("📝 <b>Quemando subtítulos…</b>\nSe actualizará el progreso durante FFmpeg.", parse_mode=enums.ParseMode.HTML)
        ok = await VideoProcessor.burn_subtitles(
            video, subtitle, output, sub_idx=state.get("sub_idx"),
            is_external=subtitle is not None,
            progress_callback=lambda text: status.edit_text(text, parse_mode=enums.ParseMode.HTML),
            crf=s["crf"], preset=s["preset"], subtitle_color="white",
            subtitle_alignment=s["alignment"], subtitle_size=20,
            subtitle_font=s["font"], watermark_color="pink", watermark_size=28,
            cancel_event=state["cancel_event"], process_holder=state["process_holder"],
            timeout=state["timeout"],
        )
        if state["cancel_event"].is_set():
            await status.edit_text("❌ Proceso cancelado.", parse_mode=enums.ParseMode.HTML)
            return
        if not ok:
            raise RuntimeError("FFmpeg no pudo generar el video final.")
        output_mb = output.stat().st_size / (1024 * 1024)
        logger.info("📤 SUBTÍTULOS LISTOS | preparando subida archivo=%s tamaño=%.2f MB", output, output_mb)
        await status.edit_text(f"✅ <b>Procesamiento terminado</b>\n📦 {output_mb:.1f} MB\n📤 Subiendo el video a Telegram…", parse_mode=enums.ParseMode.HTML)
        await message.reply_video(video=str(output), caption=f"✅ Subtítulos quemados\n🎚 CRF {s['crf']} · ⚡ {s['preset']}\n🎨 Blanco fijo · ↕️ {alignment_label(s['alignment'])}", supports_streaming=True)
        logger.info("✅ SUBIDA DE SUBTÍTULOS COMPLETADA | salida=%s", output)
        await status.delete()
    except Exception as error:
        logger.error("Error quemando subtítulos", exc_info=True)
        detail = html.escape(str(error)[:350])
        await status.edit_text(f"❌ No se pudieron quemar los subtítulos.\n<code>{detail}</code>", parse_mode=enums.ParseMode.HTML)
    finally:
        if state["user_states"].get(state["user_id"]) is state:
            state["user_states"].pop(state["user_id"], None)
        _cleanup(state)


def register(app, user_states, work_dir: Path):
    @app.on_message(filters.command("sub"))
    async def subtitle_command(client, message):
        reply = message.reply_to_message
        if not reply or not (reply.video or reply.document):
            await message.reply_text("📝 Responde a un video con /sub.")
            return
        user_id = _user_id(message)
        if user_states.get(user_id):
            await message.reply_text("⏳ Ya tienes un trabajo de subtítulos activo. Cancélalo antes de iniciar otro.")
            return
        job_dir = Path(work_dir) / f"subtitle_{user_id}_{uuid.uuid4().hex[:8]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        video_path = job_dir / safe_filename(_media_name(reply))
        status = await message.reply_text("⏳ Descargando y analizando pistas…")
        state = {"action": "burn_subtitles", "video_path": str(video_path), "job_dir": str(job_dir), "status": status, "user_id": user_id, "user_states": user_states, "cancel_event": asyncio.Event(), "process_holder": {}, "timeout": int(os.getenv("SUBTITLE_TIMEOUT", "7200"))}
        user_states[user_id] = state
        try:
            await reply.download(file_name=str(video_path))
            info = await asyncio.to_thread(VideoProcessor.probe_media, video_path)
            tracks = (info or {}).get("subtitle", [])
            if tracks:
                buttons = [[InlineKeyboardButton(t.get("label", f"Pista {t['index']}")[:fifty], callback_data=f"sub_track:{user_id}:{t['index']}")] for t in tracks[:20]]
                buttons.append([InlineKeyboardButton("📎 Usar archivo externo", callback_data=f"sub_external:{user_id}")])
                await status.edit_text("🎞 <b>Elige la pista de subtítulos</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            else:
                state["awaiting_external"] = True
                await status.edit_text("📎 Envía ahora un archivo <code>.srt</code>, <code>.ass</code> o <code>.vtt</code>.", parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            if user_states.get(user_id) is state:
                user_states.pop(user_id, None)
            _cleanup(state)
            detail = html.escape(str(error)[:300])
            await status.edit_text(f"❌ No se pudo analizar el video: <code>{detail}</code>", parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^sub_track:\d+:\d+$"))
    async def track(client, query):
        user_id = query.from_user.id; _, uid, index = query.data.split(":"); state = user_states.get(user_id)
        if not state or int(uid) != user_id: return await query.answer("Sesión expirada", show_alert=True)
        state["sub_idx"] = int(index); state["track_label"] = f"pista interna {index}"; await query.answer("Pista seleccionada"); await _show_config(query.message, state)

    @app.on_callback_query(filters.regex(r"^sub_external:\d+$"))
    async def external(client, query):
        state = user_states.get(query.from_user.id); _, uid = query.data.split(":")
        if not state or int(uid) != query.from_user.id: return await query.answer("Sesión expirada", show_alert=True)
        state["awaiting_external"] = True; await query.answer(); await query.message.edit_text("📎 Envía el archivo <code>.srt</code>, <code>.ass</code> o <code>.vtt</code>.", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.document, group=-1)
    async def subtitle_document(client, message):
        state = user_states.get(_user_id(message), {})
        if state.get("action") != "burn_subtitles" or not state.get("awaiting_external"): return
        name = safe_filename(getattr(message.document, "file_name", "subtitles.srt")); ext = Path(name).suffix.lower()
        if ext not in _SUBTITLE_EXTENSIONS: return await message.reply_text("❌ Solo se admiten .srt, .ass o .vtt.")
        path = Path(state["job_dir"]) / name; await message.download(file_name=str(path)); state["external_subtitle"] = str(path); state["track_label"] = name; state["awaiting_external"] = False; await _show_config(message, state, "✅ Subtítulo recibido")

    @app.on_callback_query(filters.regex(r"^submenu:(align|font|preset|crf|bitrate|translate):\d+$"))
    async def submenu(client, query):
        _, kind, uid = query.data.split(":"); state = user_states.get(query.from_user.id)
        if not state or int(uid) != query.from_user.id: return await query.answer("Sesión expirada", show_alert=True)
        s = _settings(state); rows = []
        if kind == "align": rows = [[InlineKeyboardButton(label, callback_data=f"subset:alignment:{key}:{uid}")] for key, (label, _) in ALIGNMENTS.items()]
        elif kind == "font": rows = [[InlineKeyboardButton(label, callback_data=f"subset:font:{key}:{uid}")] for key, (label, _) in FONTS.items()]
        elif kind == "preset": rows = [[InlineKeyboardButton(v, callback_data=f"subset:preset:{v}:{uid}") for v in ("ultrafast", "veryfast", "fast", "medium")]]
        elif kind == "crf": rows = [[InlineKeyboardButton(str(v), callback_data=f"subset:crf:{v}:{uid}") for v in (18,20,23,26,28,30)]]
        elif kind == "bitrate": await query.answer("Con CRF se conserva mejor la calidad; usa /press para bitrate manual", show_alert=True); return
        elif kind == "translate": rows = [[InlineKeyboardButton(label, callback_data=f"subset:language:{key}:{uid}")] for key, label in LANGUAGES.items()]
        rows.append([InlineKeyboardButton("↩️ Volver", callback_data=f"sub_back:{uid}")]); await query.message.edit_text("Selecciona una opción:", reply_markup=InlineKeyboardMarkup(rows)); await query.answer()

    @app.on_callback_query(filters.regex(r"^watermark_info:\d+$"))
    async def watermark_info(client, query):
        await query.answer("Jap Anime TX: Oleo Script Regular, blanco, borde azul de 8 px, fondo transparente y desvanecido durante 6 segundos.", show_alert=True)

    @app.on_callback_query(filters.regex(r"^subset:(alignment|font|preset|crf|language):[^:]+:\d+$"))
    async def subset(client, query):
        _, key, value, uid = query.data.split(":"); state = user_states.get(query.from_user.id)
        if not state or int(uid) != query.from_user.id: return await query.answer("Sesión expirada", show_alert=True)
        s = _settings(state); s[key] = value
        if key == "language":
            try:
                out = Path(state["job_dir"]) / f"translated_{value}.srt"
                tmp = out.with_suffix(".tmp.srt")
                await asyncio.to_thread(translate_subtitle_file, state["external_subtitle"], tmp, value)
                if not tmp.exists() or tmp.stat().st_size == 0: raise RuntimeError("La traducción produjo un archivo vacío.")
                tmp.replace(out); state["external_subtitle"] = str(out); s["translated"] = True
            except Exception as error:
                return await query.answer(f"Traducción no disponible: {str(error)[:120]}", show_alert=True)
        await query.answer("Guardado"); await _show_config(query.message, state)

    @app.on_callback_query(filters.regex(r"^sub_back:\d+$"))
    async def back(client, query):
        _, uid = query.data.split(":"); state = user_states.get(query.from_user.id)
        if state and int(uid) == query.from_user.id: await _show_config(query.message, state)
        else: await query.answer("Sesión expirada", show_alert=True)

    @app.on_callback_query(filters.regex(r"^sub_start:\d+$"))
    async def start(client, query):
        _, uid = query.data.split(":"); state = user_states.get(query.from_user.id)
        if state and int(uid) == query.from_user.id: await query.answer("Procesamiento iniciado"); await _burn(query.message, state)
        else: await query.answer("Sesión expirada", show_alert=True)

    @app.on_callback_query(filters.regex(r"^sub_cancel:\d+$"))
    async def cancel(client, query):
        _, uid = query.data.split(":")
        if int(uid) != query.from_user.id: return await query.answer("Sesión expirada", show_alert=True)
        state = user_states.get(query.from_user.id)
        if not state: return await query.answer("Sesión expirada", show_alert=True)
        state["cancel_event"].set()
        if state["process_holder"].get("process") is None:
            user_states.pop(query.from_user.id, None); _cleanup(state); await query.message.edit_text("❌ Proceso cancelado.")
        else:
            await query.message.edit_text("🛑 Cancelando FFmpeg…", parse_mode=enums.ParseMode.HTML)
        await query.answer("Cancelación solicitada")


# Evita que una variable mal escrita rompa el registro de botones.
fifty = 55
