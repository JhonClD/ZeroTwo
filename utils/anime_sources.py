"""Fuentes de anime migradas desde el descargador JavaScript.

Los extractores devuelven enlaces de servidores sin credenciales hardcodeadas.
La descarga final se delega a los descargadores existentes de ZeroTwo.
"""
from __future__ import annotations

import importlib
from urllib.parse import urlparse

SOURCES = {
    "tioanime": {"name": "TioAnime", "domains": ("tioanime.com",), "module": "handlers.tioanime_notify_handler", "scraper": "scrape_servidores"},
    "latanime": {"name": "LatAnime", "domains": ("latanime.org",), "module": "handlers.tioanime_notify_handler", "scraper": "scrape_servidores_latanime"},
    "jkanime": {"name": "JKAnime", "domains": ("jkanime.net",), "module": "handlers.jkanime_notify_handler", "scraper": "scrape_servers"},
    "animedbs": {"name": "AnimeDBS", "domains": ("animedbs.online",), "module": "handlers.animedbs_notify_handler", "scraper": "scrape_servers"},
    "monoschinos": {"name": "MonosChinos", "domains": ("monoschinos.st",), "module": "handlers.monoschinos_notify_handler", "scraper": "scrape_servers"},
}


def source_for_url(url: str) -> dict | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for source in SOURCES.values():
        if any(host == domain or host.endswith("." + domain) for domain in source["domains"]):
            return source
    return None


async def scrape_servers(url: str) -> tuple[dict | None, list[dict]]:
    source = source_for_url(url)
    if not source:
        return None, []
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
