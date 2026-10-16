"""Cliente resiliente para el flujo público de descargas de Loader.to."""
from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

PRIMARY_API = "https://p.savenow.to"
FALLBACK_API = "https://p.lbserver.xyz"
PUBLIC_API_KEY = "dfcb6d76f2f6a9894gjkege8a4ab232222"
REQUEST_TIMEOUT = 30
API_RETRIES = 3
RETRY_BASE_SECONDS = 1
POLL_ATTEMPTS = 180
POLL_INTERVAL = 3
POLL_TIMEOUT = POLL_ATTEMPTS * POLL_INTERVAL

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_SUCCESS_STATES = {"success", "completed", "complete", "done", "finished"}
_FAILURE_STATES = {"error", "failed", "failure", "cancelled", "canceled"}


class LoaderToError(RuntimeError):
    """Error controlado del flujo de Loader.to."""


def _valid_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None


def _find_download_url(data: Any, excluded_url: str | None = None) -> str | None:
    if isinstance(data, dict):
        for key in ("download_url", "download", "url", "link"):
            candidate = data.get(key)
            if isinstance(candidate, (dict, list)):
                found = _find_download_url(candidate, excluded_url)
                if found:
                    return found
            else:
                found = _valid_http_url(candidate)
                if found and found.rstrip("/") != (excluded_url or "").rstrip("/"):
                    return found
        for value in data.values():
            found = _find_download_url(value, excluded_url)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_download_url(value, excluded_url)
            if found:
                return found
    return None


def _get_title(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("title", "name"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key].strip()
        for value in data.values():
            title = _get_title(value)
            if title:
                return title
    elif isinstance(data, list):
        for value in data:
            title = _get_title(value)
            if title:
                return title
    return None


def _normalise_formats(data: Any) -> list[dict[str, str]]:
    """Normaliza las calidades que el proveedor incluya en su respuesta."""
    found: list[dict[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("formats", "qualities", "available_formats", "streams"):
                entries = value.get(key)
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            fmt = entry.get("format") or entry.get("format_id") or entry.get("id") or entry.get("quality")
                            label = entry.get("label") or entry.get("quality") or entry.get("resolution") or fmt
                        else:
                            fmt = entry
                            label = entry
                        if isinstance(fmt, str) and fmt.strip():
                            fmt = fmt.strip()
                            label = str(label or fmt).strip()
                            if not any(item["format"] == fmt for item in found):
                                found.append({"format": fmt, "label": label})
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(data)
    return found


def _request_json(
    url: str,
    params: dict[str, Any],
    timeout: int = REQUEST_TIMEOUT,
    retries: int = API_RETRIES,
) -> dict[str, Any]:
    """Realiza una consulta JSON con reintentos solo para fallos transitorios."""
    headers = {
        "User-Agent": "ZeroTwoBot/1.0 (+https://github.com/JhonClD/ZeroTwo)",
        "Accept": "application/json",
    }
    last_error: requests.RequestException | None = None

    retries = max(1, retries)
    for attempt in range(retries):
        try:
            with requests.get(url, params=params, headers=headers, timeout=timeout) as response:
                if response.status_code in _RETRYABLE_STATUS and attempt < retries - 1:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(max(float(retry_after), 0), 8) if retry_after else RETRY_BASE_SECONDS * (2 ** attempt)
                    except ValueError:
                        delay = RETRY_BASE_SECONDS * (2 ** attempt)
                    logger.warning("Loader.to HTTP %s; reintento %s/%s en %.1fs", response.status_code, attempt + 1, retries - 1, delay)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as error:
                    raise LoaderToError("Loader.to devolvió una respuesta que no es JSON válido.") from error
                if not isinstance(data, dict):
                    raise LoaderToError("Loader.to devolvió una respuesta inesperada.")
                return data
        except requests.RequestException as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            retryable = status is None or status in _RETRYABLE_STATUS
            if attempt >= retries - 1 or not retryable:
                raise
            delay = RETRY_BASE_SECONDS * (2 ** attempt)
            logger.warning("Fallo transitorio de Loader.to; reintento %s/%s en %.1fs", attempt + 1, retries - 1, delay)
            time.sleep(delay)

    if last_error:
        raise last_error
    raise LoaderToError("Loader.to no devolvió una respuesta.")


def _api_request_with_origin(params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    errors: list[requests.RequestException] = []
    for api_base in (PRIMARY_API, FALLBACK_API):
        try:
            data = _request_json(f"{api_base}/api/v2/download", params)
            return data, api_base
        except requests.RequestException as error:
            errors.append(error)
            logger.warning("No respondió el endpoint de Loader.to %s; se probará el respaldo", urlparse(api_base).netloc)

    last_error = errors[-1] if errors else None
    if last_error:
        status = getattr(getattr(last_error, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status else "fallo de conexión o timeout"
        raise LoaderToError(f"No se pudo contactar con los servidores de Loader.to ({detail}).") from last_error
    raise LoaderToError("No se pudo contactar con Loader.to.")


def _api_request(source_url: str, params: dict[str, Any]) -> dict[str, Any]:
    """Compatibilidad para las llamadas existentes dentro del proyecto."""
    return _api_request_with_origin(params)[0]


def _api_key() -> str:
    return os.getenv("LOADER_TO_APIKEY", "").strip() or PUBLIC_API_KEY


def get_available_formats(source_url: str) -> list[dict[str, str]]:
    """Consulta las calidades que Loader.to expone para una URL."""
    if not _valid_http_url(source_url):
        raise LoaderToError("La URL de origen no es válida.")
    data = _api_request(source_url, {"url": source_url, "format": "info", "apikey": _api_key()})
    return _normalise_formats(data)


def _download_sync(source_url: str, media_format: str) -> tuple[str, str | None]:
    if not _valid_http_url(source_url):
        raise LoaderToError("La URL de origen no es válida.")
    if not isinstance(media_format, str) or not media_format.strip():
        raise LoaderToError("No se indicó un formato de descarga válido.")

    params = {"url": source_url, "format": media_format.strip(), "apikey": _api_key()}
    data, api_base = _api_request_with_origin(params)
    direct_url = _find_download_url(data, source_url)
    title = _get_title(data)
    if direct_url:
        return direct_url, title

    raw_job_id = data.get("id") or data.get("job_id")
    job_id = str(raw_job_id) if raw_job_id is not None else None
    raw_progress_url = data.get("progress_url")
    progress_url = _valid_http_url(raw_progress_url)
    if not progress_url and isinstance(raw_progress_url, str) and raw_progress_url.strip():
        progress_url = _valid_http_url(urljoin(f"{api_base}/", raw_progress_url.strip()))
    if not job_id and not progress_url:
        error = data.get("error") or data.get("message") or "Loader.to no creó la descarga."
        raise LoaderToError(str(error)[:400])
    if not progress_url:
        progress_url = f"{api_base}/api/progress"

    consecutive_errors = 0
    deadline = time.monotonic() + POLL_TIMEOUT
    for attempt in range(POLL_ATTEMPTS):
        if time.monotonic() >= deadline:
            break
        progress_params = {"id": job_id} if job_id else {}
        if data.get("job_id") and not data.get("id"):
            progress_params = {"job_id": job_id}
        try:
            progress = _request_json(progress_url, progress_params, timeout=REQUEST_TIMEOUT, retries=1)
            consecutive_errors = 0
        except requests.RequestException as error:
            consecutive_errors += 1
            if consecutive_errors == 1 or consecutive_errors % 10 == 0:
                logger.warning("No se pudo consultar el progreso de Loader.to (%s); se reintentará", error)
            time.sleep(POLL_INTERVAL)
            continue

        direct_url = _find_download_url(progress, source_url)
        title = _get_title(progress) or title
        state = str(progress.get("status") or progress.get("state") or "").strip().lower()
        success = progress.get("success")
        if direct_url and (success in (None, 1, True, "1", "true") or state in _SUCCESS_STATES):
            return direct_url, title

        error_text = progress.get("error")
        if state in _FAILURE_STATES or error_text:
            raise LoaderToError(str(error_text or f"La descarga terminó con estado {state}.")[:400])

        if attempt < POLL_ATTEMPTS - 1:
            time.sleep(POLL_INTERVAL)

    raise LoaderToError("Loader.to tardó demasiado en preparar el archivo. Intenta nuevamente en unos minutos.")


async def download_url(source_url: str, media_format: str) -> tuple[str, str | None]:
    """Solicita una URL final de descarga para YouTube, Facebook u otra fuente."""
    import asyncio

    if not _valid_http_url(source_url):
        raise LoaderToError("La URL de origen no es válida.")
    return await asyncio.to_thread(_download_sync, source_url, media_format)
