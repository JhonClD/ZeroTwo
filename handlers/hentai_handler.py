"""Descargador HentaiLA migrado sin credenciales incrustadas."""
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

logger = logging.getLogger(__name__)
BASE_URL = "https://hentaila.com"


async def _get(url: str):
    return await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)


async def _find_media(query: str, episode: int) -> tuple[str, str] | None:
    search = await _get(f"{BASE_URL}/busqueda?q={quote_plus(query)}")
    search.raise_for_status()
    soup = BeautifulSoup(search.text, "html.parser")
    candidates = []
    for anchor in soup.select("a[href*='/media/']"):
        href = urljoin(BASE_URL, anchor.get("href", ""))
        if href.rstrip("/").endswith(f"/{episode}"):
            candidates.append((href, anchor.get_text(" ", strip=True) or query))
    if candidates:
        return candidates[0]
    # Fallback: probar el slug más obvio generado desde la búsqueda.
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    url = f"{BASE_URL}/media/{slug}/{episode}"
    response = await _get(url)
    if response.ok and "404" not in response.text[:1000]:
        return url, query
    return None


async def _download_episode(media_url: str, output_dir: Path, progress) -> tuple[bool, Path | None, str | None]:
    response = await _get(media_url)
    response.raise_for_status()
    text = response.text
    links = []
    for pattern, name in ((r"https?://[^\"'\s<>]*mega\.nz/[^\"'\s<>]+", "mega"), (r"https?://[^\"'\s<>]*mediafire\.com/file[^\"'\s<>]+", "mediafire")):
        for link in re.findall(pattern, text, re.I):
            if link not in [item[1] for item in links]:
                links.append((name, link))
    for name, link in links:
        if name == "mega":
            ok, path, error = await MEGADownloader.download(link, output_dir, progress)
        else:
            ok, path, error = await MediaFireDownloader.download(link, output_dir, progress)
        if ok and path:
            return True, path, None
        logger.warning("HentaiLA %s falló: %s", name, error)
    return False, None, "No se encontraron enlaces directos disponibles en HentaiLA"


def register(app, download_dir):
    @app.on_message(filters.command(["hdl", "hentai"] ))
    async def hentai_download(client, message: Message):
        args = message.text.split()
        if len(args) < 3 or not args[-1].isdigit():
            await message.reply_text("🔞 Uso: <code>/hdl nombre del anime episodio</code>", parse_mode=enums.ParseMode.HTML)
            return
        episode = int(args[-1])
        query = " ".join(args[1:-1])
        status = await message.reply_text("🔎 <b>Buscando en HentaiLA…</b>", parse_mode=enums.ParseMode.HTML)
        try:
            found = await _find_media(query, episode)
            if not found:
                await status.edit_text("❌ No encontré ese anime o episodio en HentaiLA.")
                return
            media_url, title = found
            user_dir = download_dir / f"user_{message.from_user.id}"
            user_dir.mkdir(parents=True, exist_ok=True)
            async def progress(text):
                try:
                    await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
            ok, path, error = await _download_episode(media_url, user_dir, progress)
            if not ok or not path:
                await status.edit_text(f"❌ {html.escape(error or 'No se pudo descargar')}", parse_mode=enums.ParseMode.HTML)
                return
            await message.reply_video(video=str(path), caption=f"🔞 {title} · Episodio {episode}", supports_streaming=True)
            await status.delete()
            path.unlink(missing_ok=True)
        except Exception as error:
            logger.exception("Error en /hdl")
            await status.edit_text(f"❌ Error: {html.escape(str(error)[:300])}", parse_mode=enums.ParseMode.HTML)
