"""Optional FlareSolverr helpers for HTTP responses protected by Cloudflare.

Set FLARESOLVERR_URL to enable challenge solving. It may be either the
FlareSolverr base URL or its /v1 endpoint. Keep the service on a private
network; never expose it directly to the public internet.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = (15, 120)
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "cloudflare ray id",
    "attention required! | cloudflare",
    "cf-browser-verification",
)


class CloudflareError(RuntimeError):
    """A challenge or invalid response prevented a media download."""


def _solver_endpoint() -> str | None:
    value = os.getenv("FLARESOLVERR_URL", "").strip()
    if not value:
        return None
    value = value.rstrip("/")
    return value if value.endswith("/v1") else f"{value}/v1"


def _looks_like_challenge(status: int, headers: Any, body: bytes) -> bool:
    content_type = str(headers.get("Content-Type", "")).lower()
    text = body[:16384].decode("utf-8", errors="ignore").lower()
    return (
        status in (403, 503)
        or any(marker in text for marker in CHALLENGE_MARKERS)
        or ("text/html" in content_type and bool(body.strip()))
    )


def _is_html_response(headers: Any, body: bytes) -> bool:
    content_type = str(headers.get("Content-Type", "")).lower()
    prefix = body[:2048].lstrip().lower()
    return "text/html" in content_type or prefix.startswith(
        (b"<!doctype html", b"<html", b"<head", b"<body")
    )


def _get_solved_session(url: str) -> requests.Session:
    endpoint = _solver_endpoint()
    if not endpoint:
        raise CloudflareError(
            "El servidor devolvió una respuesta bloqueada o un desafío de Cloudflare. "
            "Define FLARESOLVERR_URL para habilitar el servicio opcional."
        )
    max_timeout = int(os.getenv("FLARESOLVERR_MAX_TIMEOUT", "60000"))
    try:
        response = requests.post(
            endpoint,
            json={"cmd": "request.get", "url": url, "maxTimeout": max_timeout},
            timeout=(15, max_timeout / 1000 + 30),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise CloudflareError(f"No se pudo contactar FlareSolverr: {error}") from error

    solution = data.get("solution") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("status") != "ok" or not isinstance(solution, dict):
        message = data.get("message", "respuesta sin solución") if isinstance(data, dict) else "respuesta inesperada"
        raise CloudflareError(f"FlareSolverr no resolvió el desafío: {message}")
    if int(solution.get("status", 0)) >= 400:
        raise CloudflareError(f"FlareSolverr devolvió HTTP {solution.get('status')}")

    session = requests.Session()
    user_agent = solution.get("userAgent")
    if user_agent:
        session.headers["User-Agent"] = user_agent
    for cookie in solution.get("cookies", []):
        if not isinstance(cookie, dict) or not cookie.get("name"):
            continue
        session.cookies.set(
            cookie["name"], cookie.get("value", ""),
            domain=cookie.get("domain") or None,
            path=cookie.get("path") or "/",
        )
    return session


def _request_url(url: str, params: dict[str, Any] | None) -> str:
    prepared = requests.Request("GET", url, params=params).prepare()
    return prepared.url or url


def get_with_fallback(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: Any = 60,
) -> requests.Response:
    """Perform a GET, retrying a detected Cloudflare challenge via FlareSolverr."""
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    body = response.content[:16384]
    if not _looks_like_challenge(response.status_code, response.headers, body):
        return response
    if not _solver_endpoint():
        return response
    logger.warning("Desafío/bloqueo HTTP detectado; intentando con FlareSolverr")
    session = _get_solved_session(_request_url(url, params))
    retry_headers = dict(headers or {})
    retry_headers.pop("User-Agent", None)
    return session.get(url, params=params, headers=retry_headers, timeout=timeout)


def _write_stream(
    response: requests.Response,
    destination: Path,
    first_chunk: bytes,
    remaining: Iterator[bytes],
) -> int:
    response.raise_for_status()
    if _looks_like_challenge(response.status_code, response.headers, first_chunk):
        raise CloudflareError("El servidor sigue devolviendo una página de desafío")
    if _is_html_response(response.headers, first_chunk):
        raise CloudflareError("El servidor devolvió HTML en lugar de un archivo multimedia")
    if not first_chunk:
        raise CloudflareError("La descarga devolvió un archivo vacío")

    destination.parent.mkdir(parents=True, exist_ok=True)
    size = len(first_chunk)
    with destination.open("wb") as output:
        output.write(first_chunk)
        for chunk in remaining:
            if chunk:
                output.write(chunk)
                size += len(chunk)
    if size < 1024:
        destination.unlink(missing_ok=True)
        raise CloudflareError(f"La descarga es demasiado pequeña ({size} bytes), parece incompleta")
    return size


def _consume_response(response: requests.Response, destination: Path) -> int:
    iterator = response.iter_content(chunk_size=64 * 1024)
    first_chunk = next(iterator, b"")
    return _write_stream(response, destination, first_chunk, iterator)


def download_file(url: str, destination: str | Path, timeout: Any = DEFAULT_TIMEOUT) -> int:
    """Download media; retry with FlareSolverr only when a challenge is detected."""
    path = Path(destination)
    try:
        response = requests.get(url, stream=True, timeout=timeout)
    except requests.RequestException as error:
        raise CloudflareError(f"No se pudo descargar el archivo: {error}") from error

    try:
        response.raise_for_status()
        iterator = response.iter_content(chunk_size=64 * 1024)
        first_chunk = next(iterator, b"")
        if _looks_like_challenge(response.status_code, response.headers, first_chunk):
            response.close()
            logger.warning("Desafío Cloudflare en URL multimedia; intentando con FlareSolverr")
            session = _get_solved_session(url)
            solved_response = session.get(url, stream=True, timeout=timeout)
            try:
                return _consume_response(solved_response, path)
            finally:
                solved_response.close()
        return _write_stream(response, path, first_chunk, iterator)
    except requests.RequestException as error:
        if error.response is not None and _looks_like_challenge(
            error.response.status_code, error.response.headers, b""
        ):
            response.close()
            session = _get_solved_session(url)
            solved_response = session.get(url, stream=True, timeout=timeout)
            try:
                return _consume_response(solved_response, path)
            finally:
                solved_response.close()
        raise CloudflareError(f"Error HTTP descargando el archivo: {error}") from error
    finally:
        response.close()
