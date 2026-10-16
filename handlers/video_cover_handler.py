"""Portadas personales de Telegram para videos enviados al bot."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pyrogram import filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


def _send_video_by_file_id(bot_token: str, payload: dict) -> dict:
    """Llama sendVideo con IDs existentes; no transfiere bytes del video."""
    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            result = json.loads(error.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Telegram Bot API rechazó el envío del video.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("No se pudo conectar con Telegram Bot API para enviar el video.") from None
    if not isinstance(result, dict) or not result.get("ok"):
        description = result.get("description", "error sin detalle") if isinstance(result, dict) else "respuesta no válida"
        raise RuntimeError(f"Telegram no pudo reutilizar el video con portada: {description}")
    return result


def _bot_api_entities(entities) -> str | None:
    """Serializa entidades Pyrogram al JSON de Bot API, conservando formato del caption."""
    if not entities:
        return None
    serialized = []
    for entity in entities:
        item = {
            "type": getattr(entity.type, "name", str(entity.type)).lower(),
            "offset": entity.offset,
            "length": entity.length,
        }
        for name in ("url", "language", "custom_emoji_id"):
            value = getattr(entity, name, None)
            if value is not None:
                item[name] = str(value) if name == "custom_emoji_id" else value
        user = getattr(entity, "user", None)
        if user is not None:
            item["user"] = {
                "id": user.id,
                "is_bot": bool(getattr(user, "is_bot", False)),
                "first_name": getattr(user, "first_name", "Usuario") or "Usuario",
            }
            for name in ("last_name", "username", "language_code"):
                value = getattr(user, name, None)
                if value is not None:
                    item["user"][name] = value
        serialized.append(item)
    return json.dumps(serialized, ensure_ascii=False)


def register(app, work_dir: Path, bot_token: str) -> None:
    """Registra el flujo de portada; la base local solo guarda Telegram file_id."""
    root = Path(work_dir) / "video_covers"
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "covers.json"
    settings_path = root / "settings.json"
    try:
        raw = json.loads(db_path.read_text(encoding="utf-8")) if db_path.exists() else {}
        covers: dict[str, str] = {
            str(user_id): str(file_id)
            for user_id, file_id in raw.items()
            if isinstance(file_id, str) and file_id
        } if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("No se pudo leer la base local de portadas: %s", error)
        covers = {}
    try:
        raw_settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
        disabled_users = set(map(str, raw_settings.get("disabled_users", []))) if isinstance(raw_settings, dict) else set()
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as error:
        logger.warning("No se pudo leer la configuración de portadas: %s", error)
        disabled_users = set()

    db_lock = asyncio.Lock()
    user_locks: dict[int, asyncio.Lock] = {}
    try:
        max_video_mb = max(50, min(2048, int(os.getenv("ZERO_TWO_COVER_MAX_MB", "1800"))))
    except ValueError:
        max_video_mb = 1800

    async def save_db() -> None:
        async with db_lock:
            temp_path = db_path.with_suffix(".json.tmp")
            await asyncio.to_thread(
                temp_path.write_text,
                json.dumps(covers, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            await asyncio.to_thread(temp_path.replace, db_path)

    async def save_settings() -> None:
        async with db_lock:
            temp_path = settings_path.with_suffix(".json.tmp")
            data = json.dumps({"disabled_users": sorted(disabled_users)}, ensure_ascii=False, indent=2)
            await asyncio.to_thread(temp_path.write_text, data, encoding="utf-8")
            await asyncio.to_thread(temp_path.replace, settings_path)

    def owner_key(message: Message) -> str | None:
        return str(message.from_user.id) if message.from_user else None

    @app.on_message(filters.command("thumon"), group=10)
    async def enable_cover(client, message: Message):
        key = owner_key(message)
        if not key:
            await message.reply_text("No pude identificar tu cuenta de Telegram.")
            return
        if key not in disabled_users:
            await message.reply_text("Las portadas ya están activas. Envíame una foto para guardarla o cambiarla.")
            return
        disabled_users.discard(key)
        try:
            await save_settings()
        except OSError as error:
            disabled_users.add(key)
            logger.exception("No se pudo activar la preferencia de portada")
            await message.reply_text(f"No se pudo guardar el cambio en el hosting: {error}")
            return
        await message.reply_text("✅ Portadas activadas. Se aplicará tu miniatura a los videos que envíes.")

    @app.on_message(filters.command("thumoff"), group=10)
    async def disable_cover(client, message: Message):
        key = owner_key(message)
        if not key:
            await message.reply_text("No pude identificar tu cuenta de Telegram.")
            return
        if key in disabled_users:
            await message.reply_text("Las portadas ya están desactivadas. Usa /thumon para activarlas.")
            return
        disabled_users.add(key)
        try:
            await save_settings()
        except OSError as error:
            disabled_users.discard(key)
            logger.exception("No se pudo desactivar la preferencia de portada")
            await message.reply_text(f"No se pudo guardar el cambio en el hosting: {error}")
            return
        await message.reply_text("⏸ Portadas desactivadas. Tus fotos guardadas se conservan; usa /thumon para volver a activarlas.")

    @app.on_message(filters.command("show_cover"), group=10)
    async def show_cover(client, message: Message):
        key = owner_key(message)
        file_id = covers.get(key) if key else None
        if not file_id:
            await message.reply_text("No tienes portada guardada. Envíame una foto primero.")
            return
        await message.reply_photo(file_id, caption="Tu portada actual para los videos.")

    @app.on_message(filters.command("del_cover"), group=10)
    async def delete_cover(client, message: Message):
        key = owner_key(message)
        previous_cover = covers.pop(key, None) if key else None
        if previous_cover is None:
            await message.reply_text("No tienes ninguna portada guardada.")
            return
        try:
            await save_db()
        except OSError as error:
            covers[key] = previous_cover
            logger.exception("No se pudo eliminar la portada de la base local")
            await message.reply_text(f"No se pudo eliminar la portada por un error de almacenamiento: {error}")
            return
        await message.reply_text("🗑 Portada eliminada.")

    @app.on_message(filters.photo, group=10)
    async def save_cover(client, message: Message):
        key = owner_key(message)
        if not key:
            await message.reply_text("No pude identificar tu cuenta de Telegram.")
            return
        photo = message.photo
        if isinstance(photo, (list, tuple)):
            photo = photo[-1] if photo else None
        file_id = getattr(photo, "file_id", None)
        if not file_id:
            await message.reply_text("No pude leer la foto. Envíala nuevamente como foto de Telegram.")
            return
        previous_cover = covers.get(key)
        covers[key] = file_id
        try:
            await save_db()
        except OSError as error:
            if previous_cover is None:
                covers.pop(key, None)
            else:
                covers[key] = previous_cover
            logger.exception("No se pudo guardar la portada")
            await message.reply_text(f"No se pudo guardar la portada en el almacenamiento del hosting: {error}")
            return
        await message.reply_text("Portada guardada. Cuando envíes un video, lo reenviaré con esa miniatura. Usa /show_cover o /del_cover.")

    @app.on_message(filters.video | filters.document, group=10)
    async def add_cover(client, message: Message):
        key = owner_key(message)
        if not key or key in disabled_users:
            return
        file_id = covers.get(key)
        if not file_id:
            return
        media = message.video or message.document
        if not media:
            return
        if message.document and (
            not str(getattr(media, "mime_type", "")).startswith("video/")
            and Path(getattr(media, "file_name", "")).suffix.lower() not in _VIDEO_EXTS
        ):
            return
        reported_size = int(getattr(media, "file_size", 0) or 0)
        if not message.video and reported_size > max_video_mb * 1024 * 1024:
            await message.reply_text(f"El video supera el límite de {max_video_mb} MB para añadir una miniatura en este hosting.")
            return

        # Con Bot API actual, video y cover pueden enviarse por file_id: Telegram
        # reutiliza ambos archivos en sus servidores; no descargamos ni resubimos el MP4.
        if message.video:
            status = await message.reply_text("🖼 Aplicando portada al video en Telegram…")
            payload = {
                "chat_id": message.chat.id,
                "video": media.file_id,
                "cover": file_id,
                "supports_streaming": "true",
                "reply_parameters": json.dumps({"message_id": message.id}),
                "protect_content": "true" if message.has_protected_content else "false",
            }
            if getattr(media, "duration", None):
                payload["duration"] = media.duration
            if getattr(media, "width", None):
                payload["width"] = media.width
            if getattr(media, "height", None):
                payload["height"] = media.height
            if message.caption:
                payload["caption"] = message.caption
            entities = _bot_api_entities(message.caption_entities)
            if entities:
                payload["caption_entities"] = entities
            try:
                await asyncio.to_thread(_send_video_by_file_id, bot_token, payload)
                try:
                    await status.delete()
                except Exception:
                    pass
            except Exception as error:
                logger.warning("Bot API no pudo enviar el video reutilizando file_id: %s", error)
                try:
                    await status.edit_text(f"No se pudo poner la portada sin descargar el video: {str(error)[:400]}")
                except Exception:
                    pass
            return

        lock = user_locks.setdefault(int(key), asyncio.Lock())
        if lock.locked():
            await message.reply_text("Ya estoy preparando uno de tus videos. Espera a que termine antes de enviar otro.")
            return

        async with lock:
            status = await message.reply_text("🖼 Preparando la miniatura y el video…")
            temp_dir = None
            try:
                temp_dir = Path(tempfile.mkdtemp(prefix=f"cover_{key}_", dir=root))
                original_name = Path(getattr(media, "file_name", "video.mp4")).name
                suffix = Path(original_name).suffix.lower()
                if suffix not in _VIDEO_EXTS:
                    suffix = ".mp4"
                video_path = temp_dir / f"video{suffix}"
                cover_source = temp_dir / "cover_source"
                thumb_path = temp_dir / "thumb.jpg"

                downloaded_video = await client.download_media(message, file_name=str(video_path))
                if not downloaded_video:
                    raise RuntimeError("Telegram no entregó el video para preparar la miniatura.")
                video_path = Path(downloaded_video)
                if not video_path.is_file() or video_path.stat().st_size == 0:
                    raise RuntimeError("El archivo descargado está vacío.")
                if video_path.stat().st_size > max_video_mb * 1024 * 1024:
                    raise RuntimeError(f"El video descargado supera el límite de {max_video_mb} MB.")

                downloaded_cover = await client.download_media(file_id, file_name=str(cover_source))
                if not downloaded_cover:
                    raise RuntimeError("No se pudo recuperar tu portada guardada.")
                cover_source = Path(downloaded_cover)
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(cover_source), "-frames:v", "1",
                    "-vf", "scale=320:320:force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-q:v", "5", "-f", "image2", str(thumb_path),
                ]
                result = await asyncio.to_thread(
                    subprocess.run, command, capture_output=True, timeout=45,
                )
                if result.returncode or not thumb_path.is_file() or thumb_path.stat().st_size == 0:
                    detail = result.stderr.decode(errors="replace")[-300:]
                    raise RuntimeError("No se pudo convertir la portada a JPEG compatible con Telegram. " + detail)
                if thumb_path.stat().st_size > 200 * 1024:
                    raise RuntimeError("La miniatura preparada excede el límite de 200 KB de Telegram.")

                caption = message.caption or ""
                entities = message.caption_entities or None
                await client.send_video(
                    chat_id=message.chat.id,
                    video=str(video_path),
                    thumb=str(thumb_path),
                    caption=caption,
                    caption_entities=entities,
                    duration=getattr(media, "duration", 0) or 0,
                    width=getattr(media, "width", 0) or 0,
                    height=getattr(media, "height", 0) or 0,
                    supports_streaming=True,
                    reply_to_message_id=message.id,
                    protect_content=message.has_protected_content,
                )
                try:
                    await status.delete()
                except Exception:
                    pass
            except Exception as error:
                logger.exception("Error aplicando la portada de video para %s", key)
                try:
                    await status.edit_text(f"No se pudo reenviar el video con portada: {str(error)[:500]}")
                except Exception:
                    pass
            finally:
                if temp_dir is not None:
                    await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
