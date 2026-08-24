"""Cliente ligero para el flujo público de descargas de loader.to."""

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

PRIMARY_API = "https://p.savenow.to"
FALLBACK_API = "https://p.lbserver.xyz"
# Clave compartida por el frontend público de loader.to. Puede reemplazarse
# mediante LOADER_TO_APIKEY sin modificar el código.
PUBLIC_API_KEY = "dfcb6d76f2f6a9894gjkege8a4ab232222"


class LoaderToError(RuntimeError):
    """Error controlado del flujo de loader.to."""


def _valid_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} else None


def _find_download_url(data: Any) -> str | None:
    """Busca recursivamente una URL de descarga en respuestas variables."""
    if isinstance(data, dict):
        for key in ("download_url", "download", "url", "link"):
            candidate = data.get(key)
            if isinstance(candidate, dict):
                found = _find_download_url(candidate)
                if found:
                    return found
            else:
                found = _valid_http_url(candidate)
                if found:
                    return found
        for value in data.values():
            found = _find_download_url(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_download_url(value)
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


def _request_json(url: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "ZeroTwoBot/1.0 (+https://github.com/JhonClD/ZeroTwo)"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise LoaderToError("loader.to devolvió una respuesta inesperada")
    return data


def _download_sync(source_url: str, media_format: str) -> tuple[str, str | None]:
    api_key = os.getenv("LOADER_TO_APIKEY", PUBLIC_API_KEY)
    params = {"url": source_url, "format": media_format, "apikey": api_key}
    try:
        data = _request_json(f"{PRIMARY_API}/api/v2/download", params)
    except requests.RequestException as primary_error:
        logger.warning("loader.to primario no responde; probando dominio de respaldo")
        try:
            data = _request_json(f"{FALLBACK_API}/api/v2/download", params)
        except requests.RequestException as fallback_error:
            raise LoaderToError(f"No se pudo contactar loader.to: {fallback_error}") from primary_error

    direct_url = _find_download_url(data)
    title = _get_title(data)
    if direct_url:
        return direct_url, title

    job_id = data.get("id")
    progress_url = _valid_http_url(data.get("progress_url"))
    if not job_id and not progress_url:
        error = data.get("error") or data.get("message") or "No se creó la descarga"
        raise LoaderToError(str(error))

    if not progress_url:
        progress_url = f"{PRIMARY_API}/api/progress"

    for _ in range(90):
        progress_params = {"id": job_id} if job_id else {}
        progress = _request_json(progress_url, progress_params, timeout=30)
        direct_url = _find_download_url(progress)
        title = _get_title(progress) or title
        success = progress.get("success")
        if direct_url and (success in (None, 1, True, "1")):
            return direct_url, title
        if str(progress.get("error", "")).strip():
            raise LoaderToError(str(progress["error"]))
        asyncio.run(asyncio.sleep(2))

    raise LoaderToError("loader.to agotó el tiempo de espera")


async def download_url(source_url: str, media_format: str) -> tuple[str, str | None]:
    """Solicita una URL final de descarga para YouTube, Facebook u otra fuente."""
    if not _valid_http_url(source_url):
        raise LoaderToError("La URL de origen no es válida")
    return await asyncio.to_thread(_download_sync, source_url, media_format)
