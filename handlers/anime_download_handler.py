"""Descargador de anime con búsqueda y selección mediante botones."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import uuid
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from downloaders import MEGADownloader, MediaFireDownloader
from utils.anime_sources import order_servers, scrape_servers, source_for_url

logger = logging.getLogger(__name__)
_SESSIONS: dict[str, dict] = {}


async def _search_anime(query: str) -> list[dict]:
    """Busca títulos en VerAnimes."""
    url = f"https://wwv.veranimes.net/animes?buscar={quote_plus(query)}"
    response = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for anchor in soup.select("a[href*='/anime/']"):
        href = urljoin(url, anchor.get("href", ""))
        if href in seen:
            continue
        title = anchor.get("title") or anchor.get_text(" ", strip=True)
        if not title or href.rstrip("/").endswith("/animes"):
            continue
        seen.add(href)
        results.append({"title": title, "url": href})
    return results[:20]


async def _episodes_for_anime(anime_url: str) -> list[dict]:
    response = await asyncio.to_thread(requests.get, anime_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    text, soup = response.text, BeautifulSoup(response.text, "html.parser")
    slug = (soup.select_one("[data-sl]") or {}).get("data-sl") if soup.select_one("[data-sl]") else anime_url.rstrip("/").split("/")[-1]
    episodes: list[str] = []
    match = re.search(r"var\s+eps\s*=\s*(\[[^;]+\])", text, re.I)
    if match:
        try:
            episodes = [str(item) for item in json.loads(match.group(1))]
        except (ValueError, TypeError):
            pass
    if not episodes:
        for anchor in soup.select("a[href*='/ver/']"):
            href = urljoin(anime_url, anchor.get("href", ""))
            number = re.search(r"-(\d+)(?:/)?$", href)
            if number and number.group(1) not in episodes:
                episodes.append(number.group(1))
    return [{"number": number, "url": urljoin(anime_url, f"/ver/{slug}-{number}")} for number in episodes[:100]]


async def _download_server(server: dict, output_dir: Path, progress):
    name = f"{server.get('nombre', '')} {server.get('url', '')}".lower()
    if "mega" in name:
        return await MEGADownloader.download(server["url"], output_dir, progress)
    if "mediafire" in name:
        return await MediaFireDownloader.download(server["url"], output_dir, progress)
    return False, None, "Servidor no soportado directamente"


async def _resolve_and_download(url: str, output_dir: Path, progress):
    source, servers = await scrape_servers(url)
    if not source:
        return False, None, "El enlace no pertenece a una fuente soportada", "Anime"
    if not servers:
        return False, None, f"No se encontraron servidores en {source['name']}", source["name"]
    for server in order_servers(servers):
        if not server.get("directo"):
            continue
        ok, path, error = await _download_server(server, output_dir, progress)
        if ok and path:
            return True, path, None, source["name"]
        logger.warning("%s: servidor %s falló: %s", source["name"], server.get("nombre"), error)
    return False, None, f"No se pudo descargar desde los servidores directos de {source['name']}", source["name"]


async def _download_episode(message: Message, episode_url: str, title: str, download_dir: Path, status: Message):
    user_dir = download_dir / f"user_{message.from_user.id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    async def progress(text):
        try:
            await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass
    await progress("📥 <b>Buscando servidores…</b>")
    ok, path, error, source_name = await _resolve_and_download(episode_url, user_dir, progress)
    if not ok or not path:
        await status.edit_text(f"❌ <b>{html.escape(error or 'No se pudo descargar')}</b>", parse_mode=enums.ParseMode.HTML)
        return
    filename = path.name
    size = path.stat().st_size / (1024 * 1024)
    await status.edit_text(f"✅ <b>Descarga completa</b>\n📄 {html.escape(filename)}\n📦 {size:.1f} MB\n📤 Enviando…", parse_mode=enums.ParseMode.HTML)
    await message.reply_video(video=str(path), caption=f"✅ {source_name}\n📄 {filename}", supports_streaming=True)
    await status.delete()
    path.unlink(missing_ok=True)


def register(app, download_dir):
    @app.on_message(filters.command(["animedl", "adl"]))
    async def anime_download(client, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text("🎌 Usa <code>/animedl nombre del anime</code> o pega la URL de un episodio.", parse_mode=enums.ParseMode.HTML)
            return
        raw = args[1].strip()
        if not raw.startswith(("http://", "https://")) and not raw.rsplit(maxsplit=1)[-1].isdigit():
            status = await message.reply_text("🔎 <b>Buscando resultados…</b>", parse_mode=enums.ParseMode.HTML)
            try:
                results = await _search_anime(raw)
                if not results:
                    await status.edit_text("❌ No encontré ese anime en VerAnimes.")
                    return
                token = uuid.uuid4().hex[:10]
                _SESSIONS[token] = {"user_id": message.from_user.id, "results": results}
                buttons = [[InlineKeyboardButton(item["title"][:50], callback_data=f"adsel:{token}:{i}")] for i, item in enumerate(results)]
                await status.edit_text("🎌 <b>Resultados encontrados:</b>\nSelecciona un anime:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except Exception as error:
                await status.edit_text(f"❌ Error buscando: {html.escape(str(error)[:250])}", parse_mode=enums.ParseMode.HTML)
            return
        status = await message.reply_text("🔎 <b>Preparando episodio…</b>", parse_mode=enums.ParseMode.HTML)
        try:
            if raw.startswith(("http://", "https://")):
                if source_for_url(raw) is None:
                    await status.edit_text("❌ La URL no pertenece a una fuente de anime compatible.")
                    return
                await _download_episode(message, raw, "Anime", download_dir, status)
                return
            parts = raw.rsplit(maxsplit=1)
            query, number = parts[0], int(parts[1])
            results = await _search_anime(query)
            if not results:
                await status.edit_text("❌ No encontré ese anime en VerAnimes.")
                return
            episodes = await _episodes_for_anime(results[0]["url"])
            selected = next((item for item in episodes if item["number"] == str(number)), None)
            if not selected:
                await status.edit_text("❌ No encontré ese episodio.")
                return
            await _download_episode(message, selected["url"], results[0]["title"], download_dir, status)
        except Exception as error:
            logger.exception("Error en /animedl")
            await status.edit_text(f"❌ Error: {html.escape(str(error)[:300])}", parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^adsel:"))
    async def anime_select(client, query):
        parts = query.data.split(":")
        session = _SESSIONS.get(parts[1])
        if not session or query.from_user.id != session["user_id"]:
            await query.answer("Esta selección no es tuya o ya expiró.", show_alert=True)
            return
        await query.answer()
        item = session["results"][int(parts[2])]
        try:
            episodes = await _episodes_for_anime(item["url"])
            if not episodes:
                await query.message.edit_text("❌ No encontré episodios para ese anime.")
                return
            session["title"], session["episodes"] = item["title"], episodes
            buttons = [[InlineKeyboardButton(f"Episodio {ep['number']}", callback_data=f"adep:{parts[1]}:{i}")] for i, ep in enumerate(episodes)]
            await query.message.edit_text(f"🎌 <b>{html.escape(item['title'])}</b>\nSelecciona un episodio:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
        except Exception as error:
            await query.message.edit_text(f"❌ Error obteniendo episodios: {html.escape(str(error)[:250])}", parse_mode=enums.ParseMode.HTML)

    @app.on_callback_query(filters.regex(r"^adep:"))
    async def episode_select(client, query):
        parts = query.data.split(":")
        session = _SESSIONS.get(parts[1])
        if not session or query.from_user.id != session["user_id"]:
            await query.answer("Esta selección no es tuya o ya expiró.", show_alert=True)
            return
        await query.answer("Iniciando descarga…")
        status = await query.message.reply_text("🔎 <b>Preparando episodio…</b>", parse_mode=enums.ParseMode.HTML)
        episode = session["episodes"][int(parts[2])]
        try:
            await _download_episode(query.message, episode["url"], session["title"], download_dir, status)
        finally:
            _SESSIONS.pop(parts[1], None)

    logger.info("Anime downloader registrado")
