"""Fuentes de anime y extracción de servidores para ZeroTwo."""
from __future__ import annotations

import asyncio
import html
import importlib
import json
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "tioanime": {"name": "TioAnime", "domains": ("tioanime.com",), "module": "handlers.tioanime_notify_handler", "scraper": "scrape_servidores"},
    "latanime": {"name": "LatAnime", "domains": ("latanime.org",), "module": "handlers.tioanime_notify_handler", "scraper": "scrape_servidores_latanime"},
    "jkanime": {"name": "JKAnime", "domains": ("jkanime.net",), "module": "handlers.jkanime_notify_handler", "scraper": "scrape_servers"},
    "animedbs": {"name": "AnimeDBS", "domains": ("animedbs.online",), "module": "handlers.animedbs_notify_handler", "scraper": "scrape_servers"},
    "monoschinos": {"name": "MonosChinos", "domains": ("monoschinos.st",), "module": "handlers.monoschinos_notify_handler", "scraper": "scrape_servers"},
    "veranimes": {"name": "VerAnimes", "domains": ("veranimes.net",), "generic": True},
    "evangelion": {"name": "Evangelion-EC", "domains": ("evangelion-ec.net",), "generic": True},
    "animeav1": {"name": "AnimeAV1", "domains": ("animeav1.com",), "module": "handlers.animeav1_notify_handler", "scraper": "scrape_servers"},
    "katanime": {"name": "Katanime", "domains": ("katanime.net",), "generic": True},
}


def source_for_url(url: str) -> dict | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for source in SOURCES.values():
        if any(host == domain or host.endswith("." + domain) for domain in source["domains"]):
            return source
    return None


async def _scrape_generic(url: str) -> list[dict]:
    response = await asyncio.to_thread(
        requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    candidates, seen = [], set()

    def add(name: str, value: str, direct: bool = False):
        value = value.strip()
        if not value or not value.startswith(("http://", "https://")) or value in seen:
            return
        seen.add(value)
        candidates.append({"nombre": name, "url": value, "directo": direct})

    selectors = "a[href], iframe[src], iframe[data-src], [data-url], [data-src], [data-player]"
    for tag in soup.select(selectors):
        raw = tag.get("href") or tag.get("src") or tag.get("data-url") or tag.get("data-src") or tag.get("data-player") or ""
        if raw.startswith("//"):
            raw = "https:" + raw
        lower = raw.lower()
        if "mega.nz" in lower:
            add("mega", raw, True)
        elif "mediafire.com" in lower:
            add("mediafire", raw, True)
        elif any(host in lower for host in ("mp4upload", "filemoon", "streamwish", "streamtape", "dood", "voe", "gofile", "savefiles", "uns.bio", "byse", "vidhide", "mixdrop")):
            add("embed", raw)

    # VerAnimes publica sus descargas como JSON dentro de data-dwn.
    for tag in soup.select("[data-dwn]"):
        try:
            entries = json.loads(html.unescape(tag.get("data-dwn", "[]")))
            for entry in entries:
                if len(entry) >= 3:
                    name, value = str(entry[0]), str(entry[2])
                    lower = value.lower()
                    add(name, value, "mega.nz" in lower or "mediafire.com" in lower)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    # VerAnimes guarda algunos reproductores como hexadecimal en data-encrypt.
    for tag in soup.select("[data-encrypt], [encrypt]"):
        raw = tag.get("data-encrypt") or tag.get("encrypt") or ""
        try:
            add("embed", bytes.fromhex(raw).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
    return candidates


async def scrape_servers(url: str) -> tuple[dict | None, list[dict]]:
    source = source_for_url(url)
    if not source:
        return None, []
    if source.get("generic"):
        return source, await _scrape_generic(url)
    module = importlib.import_module(source["module"])
    scraper = getattr(module, source["scraper"])
    return source, await scraper(url)


def order_servers(servers: list[dict]) -> list[dict]:
    preferred = ("mediafire", "mega", "gofile", "savefiles", "filemoon", "streamwish", "streamtape", "dood", "voe")
    return sorted(
        servers,
        key=lambda item: (
            not item.get("directo", False),
            next((i for i, name in enumerate(preferred) if name in f"{item.get('nombre', '')} {item.get('url', '')}".lower()), 99),
        ),
    )
