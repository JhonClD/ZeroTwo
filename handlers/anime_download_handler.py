"""Descargador de anime migrado desde anime-DL.js."""
from __future__ import annotations

import asyncio
import html
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from pyrogram import enums, filters
from pyrogram.types import Message

from downloaders import MEGADownloader, MediaFireDownloader
from utils.anime_sources import order_servers, scrape_servers, source_for_url

logger = logging.getLogger(__name__)


def _safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()[:120] or "anime"


async def _search_anime(query: str) -> list[dict]:
    """Busca títulos y episodios en AnimeFLV como índice público."""
    url = f"https://www3.animeflv.net/browse?q={quote_plus(query)}"
    response = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for card in soup.select("ul.ListAnimes li, article.Anime, .Anime")[:12]:
        anchor = card.select_one("a[href*='/anime/']")
        if not anchor:
            continue
        results.append({"title": anchor.get("title") or anchor.get_text(" ", strip=True), "url": urljoin(url, anchor["href"])})
    return results


async def _episode_url(anime_url: str, episode: int) -> str | None:
    response = await asyncio.to_thread(requests.get, anime_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    patterns = (f"/episode/{episode}", f"/ver/{episode}", f"-{episode}")
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        text = anchor.get_text(" ", strip=True)
        if any(pattern in href.lower() for pattern in patterns) or re.search(rf"(?:episodio|episode|capitulo)[- ]?{episode}(?:\D|$)", text, re.I):
            return urljoin(anime_url, href)
    return None


async def _download_server(server: dict, output_dir: Path, progress) -> tuple[bool, Path | None, str | None]:
    name = f"{server.get('nombre', '')} {server.get('url', '')}".lower()
    if "mega" in name:
        return await MEGADownloader.download(server["url"], output_dir, progress)
    if "mediafire" in name:
        return await MediaFireDownloader.download(server["url"], output_dir, progress)
    return False, None, "Servidor no soportado directamente"


async def _resolve_and_download(url: str, output_dir: Path, progress) -> tuple[bool, Path | None, str | None, str]:
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


def register(app, download_dir):
    @app.on_message(filters.command(["animedl", "adl"]))
    async def anime_download(client, message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text(
                "🎌 <b>Anime Downloader</b>\n\n"
                "<code>/animedl URL_DEL_EPISODIO</code>\n"
                "<code>/animedl URL_DEL_ANIME 1</code>\n"
                "<code>/animedl nombre del anime 1</code>\n\n"
                "Fuentes: TioAnime, LatAnime, JKAnime, AnimeDBS y MonosChinos.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        raw = args[1].strip()
        status = await message.reply_text("🔎 <b>Preparando episodio…</b>", parse_mode=enums.ParseMode.HTML)
        try:
            episode_url = raw
            title = "Anime"
            if not raw.startswith(("http://", "https://")):
                parts = raw.rsplit(maxsplit=1)
                if len(parts) != 2 or not parts[1].isdigit():
                    await status.edit_text("❌ Usa una URL de episodio o: <code>/animedl nombre del anime 1</code>", parse_mode=enums.ParseMode.HTML)
                    return
                query, number = parts[0], int(parts[1])
                results = await _search_anime(query)
                if not results:
                    await status.edit_text("❌ No encontré ese anime en el buscador.")
                    return
                anime = results[0]
                title = anime["title"]
                episode_url = await _episode_url(anime["url"], number)
                if not episode_url:
                    await status.edit_text("❌ No encontré ese episodio en la página del anime.")
                    return
            elif source_for_url(raw) is None:
                await status.edit_text("❌ La URL no pertenece a una fuente de anime compatible.")
                return
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
        except Exception as error:
            logger.exception("Error en /animedl")
            await status.edit_text(f"❌ Error: {html.escape(str(error)[:300])}", parse_mode=enums.ParseMode.HTML)

    logger.info("Anime downloader registrado")
