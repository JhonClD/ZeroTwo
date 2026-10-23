"""Acceso a JKAnime con la cadena de fetch usada por Hentai-DL.

Las credenciales se leen únicamente del entorno del proceso. No se incrustan
claves en el repositorio. Las URLs se restringen al dominio de JKAnime.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

CACHE_TTL = 6 * 60 * 60
CACHE_MAX = 150
REQUEST_DELAY = 2.0
_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_request_lock = threading.Lock()
_last_request_time = 0.0


class JKAnimeFetchError(RuntimeError):
    """No fue posible obtener una página de JKAnime con las capas configuradas."""


def _allowed_url(url: str) -> bool:
    try:
        hostname = (urlparse(url).hostname or "").lower()
        return hostname == "jkanime.net" or hostname.endswith(".jkanime.net")
    except (TypeError, ValueError):
        return False


def _looks_blocked(body: str, url: str) -> bool:
    if not body:
        return True
    if re.search(r"cloudflare|challenge-platform|cf-browser-verification|just a moment|enable javascript and cookies|cf_clearance", body, re.I):
        return True
    path = urlparse(url).path.lower()
    if "/api/" in path or "/ajax/" in path:
        try:
            json.loads(body)
            return False
        except (TypeError, ValueError):
            pass
    return len(body) < 200


def _cache_get(url: str) -> str | None:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(url)
        if not entry:
            return None
        created, body = entry
        if now - created > CACHE_TTL:
            _cache.pop(url, None)
            return None
        return body


def _cache_set(url: str, body: str) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest, None)
        _cache[url] = (time.monotonic(), body)


def _get_text(provider: str, endpoint: str, target_url: str, *, params=None,
              headers=None, timeout: int = 25) -> tuple[str | None, str | None]:
    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers or BASE_HEADERS,
            timeout=timeout,
        )
        if not response.ok:
            return None, f"{provider} HTTP {response.status_code}"
        body = response.text
        if _looks_blocked(body, target_url):
            return None, f"{provider} devolvió una página bloqueada o vacía"
        return body, None
    except requests.RequestException as error:
        # No imprimir URLs completas: algunas capas llevan credenciales en query params.
        return None, f"{provider} {type(error).__name__}"


def _fetch_sync(url: str, headers: dict | None, timeout: int) -> str:
    if not _allowed_url(url):
        raise ValueError("El fetch compartido solo admite URLs de jkanime.net")

    cached = _cache_get(url)
    if cached is not None:
        return cached

    failures: list[str] = []
    request_headers = {**BASE_HEADERS, **(headers or {})}
    provider_timeout = max(timeout, 30)

    with _request_lock:
        cached = _cache_get(url)
        if cached is not None:
            return cached

        global _last_request_time
        wait = REQUEST_DELAY - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()

        layers = []
        scrape_do = os.environ.get("SCRAPE_DO_TOKEN", "").strip()
        if scrape_do:
            layers.append(("scrape.do", "https://api.scrape.do/", {"token": scrape_do, "url": url, "render": "false"}, None, provider_timeout))

        scraper_api = os.environ.get("SCRAPERAPI_KEY", "").strip()
        if scraper_api:
            layers.append(("ScraperAPI", "https://api.scraperapi.com/", {"api_key": scraper_api, "url": url, "render": "false"}, None, provider_timeout))

        webscraping_api = os.environ.get("WEBSCRAPINGAPI_KEY", "").strip()
        if webscraping_api:
            layers.append(("WebScrapingAPI", "https://api.webscrapingapi.com/v2", {"api_key": webscraping_api, "url": url, "render_js": "0"}, None, provider_timeout))

        scrapingdog = os.environ.get("SCRAPINGDOG_KEY", "").strip()
        if scrapingdog:
            layers.append(("Scrapingdog", "https://api.scrapingdog.com/scrape", {"api_key": scrapingdog, "url": url}, None, provider_timeout))

        scrapingbee = os.environ.get("SCRAPINGBEE_KEY", "").strip()
        if scrapingbee:
            layers.append(("ScrapingBee", "https://app.scrapingbee.com/api/v1/", {"api_key": scrapingbee, "url": url}, None, provider_timeout))

        worker = os.environ.get("CF_WORKER_URL", "").strip()
        if worker:
            endpoint = worker.rstrip("/") + "/"
            layers.append(("Cloudflare Worker", endpoint, {"url": url}, None, 30))

        # Acceso directo y proxies públicos, igual que la última parte de Hentai-DL.
        layers.append(("directo", url, None, request_headers, timeout))
        layers.extend([
            ("AllOrigins", "https://api.allorigins.win/raw", {"url": url}, None, 20),
            ("CorsProxy", "https://corsproxy.io/", {"url": url}, None, 20),
            ("CodeTabs", "https://api.codetabs.com/v1/proxy", {"quest": url}, None, 20),
            ("ThingProxy", f"https://thingproxy.freeboard.io/fetch/{url}", None, None, 20),
        ])

        for provider, endpoint, params, layer_headers, layer_timeout in layers:
            body, failure = _get_text(
                provider,
                endpoint,
                url,
                params=params,
                headers=layer_headers or request_headers,
                timeout=layer_timeout,
            )
            if body is not None:
                _cache_set(url, body)
                logger.info("[jkanime-fetch] Capa %s OK", provider)
                return body
            failures.append(failure or provider)
            logger.warning("[jkanime-fetch] Capa %s no disponible", provider)

    detail = "; ".join(failures[-8:])
    raise JKAnimeFetchError(
        "JKAnime no respondió con contenido utilizable desde este entorno tras probar la cadena de Hentai-DL. "
        f"Capas fallidas: {detail}"
    )


async def get_jkanime_text(url: str, *, headers: dict | None = None, timeout: int = 25) -> str:
    """Obtiene HTML/JSON de JKAnime sin bloquear el event loop."""
    import asyncio

    return await asyncio.to_thread(_fetch_sync, url, headers, timeout)
