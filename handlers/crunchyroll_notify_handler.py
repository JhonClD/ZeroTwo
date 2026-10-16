"""Notificaciones de episodios nuevos de Crunchyroll en Telegram.

Solo consulta metadatos del catálogo y publica enlaces oficiales; no descarga
streams, no inicia sesión con cuentas y no maneja claves DRM.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from pyrogram import enums, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

CR_BASE = "https://www.crunchyroll.com"
CR_API = "https://beta-api.crunchyroll.com"
CR_AUTH = f"{CR_BASE}/auth/v1/token"
# Client ID de modo anónimo del plugin de referencia; no es una cuenta de usuario.
BASIC_ANON = "Basic dC1rZGdwMmg4YzNqdWI4Zm4wZnE6eWZMRGZNZnJZdktYaDRKWFMxTEVJMmNDcXUxdjVXYW4="
DEVICE_ID = "00000000-dead-beef-cafe-000000000000"
DEVICE_TYPE = "ANDROIDTV"
USER_AGENT = "Crunchyroll/ANDROIDTV/3.59.0_22338 (Android 13.0; en-US; TCL-S5400AF Build/TP1A.220624.014)"
ALLOWED_LOCALES = {"ja-JP", "es-419", "es-LA", "es-ES"}
LOCALE_NAMES = {"ja-JP": "Japonés", "es-419": "Latino", "es-LA": "Latino", "es-ES": "Castellano"}

_STATE_FILE: Path | None = None
_SEEN_FILE: Path | None = None
_MONITOR_TASK: asyncio.Task | None = None
_TOKEN: str | None = None
_TOKEN_EXPIRES = 0.0
_TOKEN_LOCK = threading.Lock()
_POLL_LOCK: asyncio.Lock | None = None


def _owner_ids() -> set[int]:
    raw = os.getenv("CRUNCHYROLL_OWNER_IDS", "") or os.getenv("TIOANIME_OWNER_IDS", "")
    configured = {int(part) for part in raw.split(",") if part.strip().isdigit()}
    # ID indicado por el propietario para que el comando funcione también en
    # paneles donde no se han configurado correctamente las variables de entorno.
    return configured or {7856571519}


def _is_owner(message: Message) -> bool:
    sender = getattr(message, "from_user", None)
    return bool(sender and _owner_ids() and sender.id in _owner_ids())


def _load_json(path: Path | None, fallback):
    if path is None:
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback


def _save_json(path: Path | None, data) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        logger.exception("No se pudo guardar el estado del notificador Crunchyroll")


def _load_chats() -> list[int]:
    raw = _load_json(_STATE_FILE, {})
    chats = raw.get("target_chats", []) if isinstance(raw, dict) else []
    result = []
    for chat_id in chats:
        try:
            value = int(chat_id)
            if value not in result:
                result.append(value)
        except (TypeError, ValueError):
            continue
    return result


def _save_chats(chats: list[int]) -> None:
    _save_json(_STATE_FILE, {"target_chats": list(dict.fromkeys(int(x) for x in chats))})


def _load_seen() -> list[str]:
    value = _load_json(_SEEN_FILE, [])
    return [str(item) for item in value if isinstance(item, (str, int))] if isinstance(value, list) else []


def _save_seen(ids: list[str]) -> None:
    _save_json(_SEEN_FILE, list(dict.fromkeys(ids))[-300:])


def _get_token(session: requests.Session) -> str:
    global _TOKEN, _TOKEN_EXPIRES
    now = time.monotonic()
    if _TOKEN and now < _TOKEN_EXPIRES - 30:
        return _TOKEN
    with _TOKEN_LOCK:
        now = time.monotonic()
        if _TOKEN and now < _TOKEN_EXPIRES - 30:
            return _TOKEN
        response = session.post(
            CR_AUTH,
            headers={
                "Authorization": BASIC_ANON,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
                "ETP-Anonymous-ID": DEVICE_ID,
            },
            data={
                "grant_type": "client_id",
                "scope": "offline_access",
                "device_id": DEVICE_ID,
                "device_type": DEVICE_TYPE,
            },
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError("La respuesta anónima de Crunchyroll no incluyó un token.")
        _TOKEN = token
        _TOKEN_EXPIRES = now + max(60, int(body.get("expires_in", 300)))
        return token


def _normalize_episode(item: dict) -> dict | None:
    metadata = item.get("episode_metadata") or {}
    episode_id = str(item.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", episode_id):
        return None

    locale = item.get("audio_locale") or metadata.get("audio_locale") or ""
    if not locale:
        if episode_id.endswith("JAJP"):
            locale = "ja-JP"
        elif episode_id.endswith(("ES419", "LA")):
            locale = "es-419"
        elif episode_id.endswith("ESES"):
            locale = "es-ES"
    if locale not in ALLOWED_LOCALES:
        return None

    series = str(item.get("series_title") or metadata.get("series_title") or "").strip()
    season = str(item.get("season_title") or metadata.get("season_title") or "").strip()
    if season and series and season.lower() not in series.lower():
        series = f"{series} {season}"
    if not series:
        series = str(item.get("title") or "Anime").strip()

    ep_num = item.get("episode_number", metadata.get("episode_number"))
    episode_title = str(item.get("title") or "").strip()
    slug = str(item.get("slug_title") or metadata.get("slug_title") or "").strip()
    suffix = f"/{quote(slug, safe='-._~')}" if slug else ""
    return {
        "id": episode_id,
        "series": series,
        "title": episode_title,
        "number": ep_num if ep_num is not None else "Especial",
        "locale": locale,
        "url": f"{CR_BASE}/watch/{quote(episode_id, safe='-._~')}{suffix}",
        "image": _extract_image(item.get("images") or metadata.get("images") or {}),
    }


def _image_candidates(value) -> list[tuple[int, str]]:
    if isinstance(value, str):
        return [(0, value)]
    if isinstance(value, list):
        return [candidate for child in value for candidate in _image_candidates(child)]
    if isinstance(value, dict):
        source = value.get("source")
        if isinstance(source, str):
            try:
                width = int(value.get("width") or 0)
            except (TypeError, ValueError):
                width = 0
            return [(width, source)]
        return [candidate for child in value.values() for candidate in _image_candidates(child)]
    return []


def _extract_image(images: dict) -> str | None:
    if not isinstance(images, dict):
        return None
    for key in ("thumbnail", "poster_tall", "poster_wide"):
        candidates = sorted(_image_candidates(images.get(key)), key=lambda candidate: candidate[0], reverse=True)
        for _, url in candidates:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme == "https" and (host == "crunchyroll.com" or host.endswith(".crunchyroll.com")):
                return url
    return None


def _fetch_latest_sync() -> list[dict]:
    """Obtiene solo datos de catálogo visibles en modo anónimo."""
    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        # Inicializa cookies públicas de la web; no se envían credenciales de cuenta.
        try:
            session.get(CR_BASE, timeout=12)
        except requests.RequestException:
            pass
        token = _get_token(session)
        response = session.get(
            f"{CR_API}/content/v1/browse",
            params={"count": "100", "sort_by": "newly_added", "type": "episode", "locale": "es-419"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) and isinstance(payload, dict):
        rows = payload.get("data", [])
    episodes = []
    seen_ids = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        episode = _normalize_episode(row)
        if episode and episode["id"] not in seen_ids:
            seen_ids.add(episode["id"])
            episodes.append(episode)
    return episodes


def _format_episode(episode: dict) -> str:
    series = html.escape(episode["series"])
    title = html.escape(episode["title"])
    number = html.escape(str(episode["number"]))
    locale = html.escape(LOCALE_NAMES.get(episode["locale"], episode["locale"]))
    url = html.escape(episode["url"], quote=True)
    episode_line = f"Ep. {number}" + (f" — {title}" if title else "")
    return f"📺 <b>{series}</b>\n🎬 {episode_line}\n🌐 {locale}\n\n<a href=\"{url}\">Ver en Crunchyroll</a>"


def _interval_minutes() -> int:
    try:
        return max(1, min(1440, int(os.getenv("CR_MINUTES", "5"))))
    except ValueError:
        return 5


async def _send_episode(app, chat_id: int, episode: dict) -> None:
    caption = _format_episode(episode)
    image = episode.get("image")
    if image:
        try:
            await app.send_photo(chat_id, image, caption=caption, parse_mode=enums.ParseMode.HTML)
            return
        except Exception:
            logger.warning("Crunchyroll: no se pudo enviar la miniatura; se enviará solo el enlace.", exc_info=True)
    await app.send_message(chat_id, caption, parse_mode=enums.ParseMode.HTML)


async def _poll_once_locked(app) -> int:
    episodes = await asyncio.to_thread(_fetch_latest_sync)
    ids = [episode["id"] for episode in episodes]
    seen = _load_seen()
    if not seen:
        _save_seen(ids)
        logger.info("Crunchyroll: inicializado el registro de episodios (%d IDs).", len(ids))
        return 0

    known = set(seen)
    seen_order = list(seen)
    new_episodes = [episode for episode in episodes if episode["id"] not in known]
    chats = _load_chats()
    sent_count = 0
    for episode in reversed(new_episodes):
        delivered = False
        for chat_id in chats:
            try:
                await _send_episode(app, chat_id, episode)
                delivered = True
                await asyncio.sleep(1)
            except Exception:
                logger.exception("Crunchyroll: no se pudo enviar el aviso al chat %s", chat_id)
        if delivered:
            known.add(episode["id"])
            seen_order.append(episode["id"])
            sent_count += 1
            _save_seen(seen_order)
    return sent_count


async def _poll_once(app) -> int:
    global _POLL_LOCK
    if _POLL_LOCK is None:
        _POLL_LOCK = asyncio.Lock()
    async with _POLL_LOCK:
        return await _poll_once_locked(app)


async def _monitor_loop(app) -> None:
    while True:
        try:
            if _load_chats():
                count = await _poll_once(app)
                if count:
                    logger.info("Crunchyroll: enviados %d avisos de episodios.", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Crunchyroll: fallo al consultar el catálogo anónimo")
        await asyncio.sleep(_interval_minutes() * 60)


def register(app, work_dir: Path) -> None:
    global _STATE_FILE, _SEEN_FILE, _MONITOR_TASK
    base = Path(work_dir)
    _STATE_FILE = base / "crunchyroll_notify_state.json"
    _SEEN_FILE = base / "crunchyroll_notify_seen.json"

    if _MONITOR_TASK is None or _MONITOR_TASK.done():
        _MONITOR_TASK = app.loop.create_task(_monitor_loop(app))

    async def require_owner(message: Message) -> bool:
        if _is_owner(message):
            return True
        await message.reply_text("⛔ Solo el propietario puede administrar las notificaciones.")
        return False

    @app.on_message(filters.command("crset"))
    async def crset(client, message: Message):
        if not await require_owner(message):
            return
        chats = _load_chats()
        if message.chat.id in chats:
            return await message.reply_text("ℹ️ Este chat ya recibe avisos de Crunchyroll.")
        chats.append(message.chat.id)
        _save_chats(chats)
        await message.reply_text(f"✅ Chat añadido. Chats configurados: {len(chats)}.")

    @app.on_message(filters.command("crrem"))
    async def crrem(client, message: Message):
        if not await require_owner(message):
            return
        chats = _load_chats()
        updated = [chat_id for chat_id in chats if chat_id != message.chat.id]
        _save_chats(updated)
        if len(updated) == len(chats):
            return await message.reply_text("ℹ️ Este chat no estaba suscrito.")
        await message.reply_text(f"✅ Chat eliminado. Quedan {len(updated)} chats suscritos.")

    @app.on_message(filters.command("crstatus"))
    async def crstatus(client, message: Message):
        if not await require_owner(message):
            return
        chats = _load_chats()
        await message.reply_text(
            "📊 <b>Avisos de Crunchyroll</b>\n"
            "Modo: catálogo anónimo; no se guarda una cuenta ni contraseña.\n"
            f"Revisión: cada {_interval_minutes()} min.\n"
            f"Chats suscritos: {len(chats)}.\n"
            f"IDs en caché: {len(_load_seen())}.",
            parse_mode=enums.ParseMode.HTML,
        )

    @app.on_message(filters.command("crlist"))
    async def crlist(client, message: Message):
        if not await require_owner(message):
            return
        status = await message.reply_text("🔍 Consultando los episodios recientes de Crunchyroll…")
        try:
            episodes = await asyncio.to_thread(_fetch_latest_sync)
            if not episodes:
                return await status.edit_text("📭 No se encontraron episodios recientes en los idiomas configurados.")
            for episode in episodes[:10]:
                await _send_episode(client, message.chat.id, episode)
                await asyncio.sleep(1)
            await status.delete()
        except Exception as error:
            logger.exception("Crunchyroll: error en /crlist")
            await status.edit_text(f"❌ No se pudo consultar el catálogo: {html.escape(str(error)[:500])}")

    @app.on_message(filters.command("crnotify"))
    async def crnotify(client, message: Message):
        if not await require_owner(message):
            return
        if not _load_chats():
            return await message.reply_text("ℹ️ Primero suscribe un chat con /crset.")
        status = await message.reply_text("🔍 Revisando episodios nuevos…")
        try:
            count = await _poll_once(client)
            await status.edit_text(f"✅ Revisión terminada. Avisos nuevos enviados: {count}.")
        except Exception as error:
            logger.exception("Crunchyroll: error en /crnotify")
            await status.edit_text(f"❌ No se pudo revisar el catálogo: {html.escape(str(error)[:500])}")
