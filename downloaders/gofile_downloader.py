"""Descargas de enlaces públicos de GoFile con límites y streaming seguro."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.gofile.io"
_USER_AGENT = os.getenv(
    "GOFILE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
_LANGUAGE = os.getenv("GOFILE_LANGUAGE", "en-US")
# GoFile cambia ocasionalmente este valor dentro de su cliente web.
_WT_SALT = os.getenv("GOFILE_WT_SALT", "12af056dacea0b")
_WT_WINDOW_SECONDS = 4 * 60 * 60
_PAGE_SIZE = 1000
_MAX_PAGES = 10
_MAX_FILES = 100
_MAX_DEPTH = 5
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

_guest_token: str | None = None
_guest_token_lock = threading.Lock()


class GoFileDownloadError(Exception):
    """Error comprensible de metadata o transferencia desde GoFile."""


class GoFileDownloader:
    """Lee enlaces compartidos públicos de GoFile y descarga archivos por streaming."""

    @staticmethod
    def parse_content_id(url: str) -> str | None:
        try:
            parsed = urlsplit(url.strip())
        except (AttributeError, ValueError):
            return None
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if (parsed.hostname or "").lower() not in ("gofile.io", "www.gofile.io"):
            return None
        match = re.fullmatch(r"/d/([^/]+)/?", parsed.path, flags=re.IGNORECASE)
        if not match:
            return None
        content_id = match.group(1)
        return content_id if _ID_RE.fullmatch(content_id) else None

    @classmethod
    def is_gofile_url(cls, url: str) -> bool:
        return cls.parse_content_id(url) is not None

    @staticmethod
    def website_token(account_token: str, window_offset: int = 0) -> str:
        """Genera el token web que el cliente público de GoFile usa en /contents."""
        window = int(time.time() // _WT_WINDOW_SECONDS) + window_offset
        raw = f"{_USER_AGENT}::{_LANGUAGE}::{account_token}::{window}::{_WT_SALT}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_guest_token() -> str:
        """Crea y reutiliza un token invitado; no requiere credenciales del usuario."""
        global _guest_token
        if _guest_token:
            return _guest_token
        with _guest_token_lock:
            if _guest_token:
                return _guest_token
            try:
                response = requests.post(
                    f"{_API_BASE}/accounts",
                    json={},
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Origin": "https://gofile.io",
                        "Content-Type": "application/json",
                    },
                    timeout=(10, 30),
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as error:
                raise GoFileDownloadError(
                    "No pude conectar con GoFile para crear la sesión invitada. "
                    "El hosting podría bloquear la conexión saliente."
                ) from error
            except (ValueError, TypeError) as error:
                raise GoFileDownloadError("GoFile respondió con datos inválidos al iniciar la sesión.") from error

            token = (payload.get("data") or {}).get("token") if payload.get("status") == "ok" else None
            if not token:
                status = payload.get("status", "respuesta desconocida")
                raise GoFileDownloadError(f"GoFile no permitió iniciar la sesión invitada ({status}).")
            _guest_token = str(token)
            return _guest_token

    @classmethod
    def _fetch_content(cls, content_id: str, page: int = 1) -> dict:
        """Obtiene metadata pública con reintento para rotación del token y rate limit."""
        global _guest_token
        offsets = (0, -1)
        for attempt in range(4):
            token = cls._get_guest_token()
            offset = offsets[min(attempt, len(offsets) - 1)]
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Website-Token": cls.website_token(token, offset),
                "X-BL": _LANGUAGE,
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://gofile.io",
                "Referer": "https://gofile.io/",
            }
            params = {
                "contentFilter": "",
                "page": page,
                "pageSize": _PAGE_SIZE,
                "sortField": "createTime",
                "sortDirection": -1,
            }
            try:
                response = requests.get(
                    f"{_API_BASE}/contents/{content_id}",
                    headers=headers,
                    params=params,
                    timeout=(10, 45),
                )
                payload = response.json()
            except requests.RequestException as error:
                detail = str(error).lower()
                if any(hint in detail for hint in ("connection reset", "connection aborted", "remote end closed")):
                    reason = "La red del hosting (frecuentemente IPs de centros de datos) podría estar bloqueada por GoFile."
                else:
                    reason = "Revisa la conexión saliente del hosting e inténtalo de nuevo."
                raise GoFileDownloadError(f"GoFile no respondió al consultar el enlace. {reason}") from error
            except (ValueError, TypeError) as error:
                if getattr(response, "status_code", 0) == 429 and attempt < 3:
                    time.sleep(attempt + 1)
                    continue
                raise GoFileDownloadError("GoFile devolvió una respuesta JSON inválida.") from error

            status = payload.get("status")
            if response.status_code == 429:
                status = "error-rateLimit"
            if status == "ok":
                response.raise_for_status()
                return payload
            if status == "error-rateLimit" and attempt < 3:
                time.sleep(attempt + 1)
                continue
            if status == "error-token" and attempt == 0:
                with _guest_token_lock:
                    _guest_token = None
                continue
            if status == "error-notPremium" and attempt == 0:
                continue
            if status in ("error-notFound", "error-notPublic"):
                raise GoFileDownloadError("El enlace no existe, venció o no es público.")
            if status == "error-notPremium":
                raise GoFileDownloadError(
                    "GoFile rechazó el token web invitado. Es posible que haya cambiado su API; "
                    "actualiza el bot y vuelve a intentarlo."
                )
            if status == "error-passwordRequired":
                raise GoFileDownloadError("El enlace está protegido con contraseña y esta versión no admite ese caso.")
            raise GoFileDownloadError(f"GoFile rechazó la consulta ({status or 'error desconocido'}).")
        raise GoFileDownloadError("GoFile limitó demasiadas consultas seguidas. Espera un momento y reintenta.")

    @classmethod
    def list_shared_files(cls, url: str) -> dict:
        """Devuelve archivos de un share individual o carpeta pública."""
        content_id = cls.parse_content_id(url)
        if not content_id:
            raise GoFileDownloadError("El enlace debe tener el formato público https://gofile.io/d/ID.")

        root_payload = cls._fetch_content(content_id)
        root = root_payload.get("data") or {}
        files = []
        seen = set()
        requests_used = [1]

        def add_file(entry: dict, fallback_id: str = ""):
            item = dict(entry)
            item.setdefault("id", fallback_id)
            item_id = str(item.get("id") or fallback_id)
            unique_key = item_id or str(item.get("name") or "")
            link = item.get("link")
            if link and cls._is_storage_url(link) and unique_key not in seen:
                item["id"] = item_id
                item["name"] = cls._safe_filename(item.get("name"), item_id)
                try:
                    item["size"] = max(0, int(item.get("size") or 0))
                except (TypeError, ValueError):
                    item["size"] = 0
                files.append(item)
                seen.add(unique_key)

        def collect(folder_data: dict, depth: int = 0):
            if len(files) >= _MAX_FILES:
                return
            if folder_data.get("type") == "file":
                entry_id = str(folder_data.get("id") or content_id)
                item = dict(folder_data)
                if not item.get("link") and entry_id:
                    requests_used[0] += 1
                    if requests_used[0] <= _MAX_FILES:
                        detail = cls._fetch_content(entry_id).get("data") or {}
                        item.update(detail)
                add_file(item, entry_id)
                return
            if folder_data.get("type") != "folder":
                raise GoFileDownloadError("GoFile devolvió un tipo de contenido no compatible.")
            if depth > _MAX_DEPTH:
                return

            total_pages = 1
            for page in range(1, _MAX_PAGES + 1):
                if page > total_pages:
                    break
                if page == 1 and folder_data.get("children") is not None:
                    page_data = folder_data
                else:
                    requests_used[0] += 1
                    if requests_used[0] > _MAX_FILES:
                        return
                    page_payload = cls._fetch_content(str(folder_data.get("id") or content_id), page)
                    page_data = page_payload.get("data") or {}
                children = page_data.get("children") or page_data.get("contents") or {}
                if isinstance(children, dict):
                    child_items = list(children.items())
                elif isinstance(children, list):
                    child_items = [(str(item.get("id") or index), item) for index, item in enumerate(children)]
                else:
                    child_items = []
                for child_id, child in child_items:
                    if len(files) >= _MAX_FILES or not isinstance(child, dict):
                        break
                    item = dict(child)
                    item_id = str(item.get("id") or child_id)
                    if item.get("type") == "folder":
                        if depth >= _MAX_DEPTH:
                            continue
                        requests_used[0] += 1
                        if requests_used[0] > _MAX_FILES:
                            return
                        nested = cls._fetch_content(item_id).get("data") or {}
                        collect(nested, depth + 1)
                    else:
                        if not item.get("link"):
                            requests_used[0] += 1
                            if requests_used[0] <= _MAX_FILES:
                                detail = cls._fetch_content(item_id).get("data") or {}
                                item.update(detail)
                        add_file(item, item_id)
                metadata = page_payload.get("metadata") if page > 1 else root_payload.get("metadata")
                try:
                    total_pages = max(1, min(_MAX_PAGES, int((metadata or {}).get("totalPages") or 1)))
                except (TypeError, ValueError):
                    total_pages = 1
                if not page_data.get("children") and not page_data.get("contents"):
                    break

        collect(root)
        if not files:
            raise GoFileDownloadError("No encontré archivos descargables en ese enlace público de GoFile.")
        return {
            "content_id": content_id,
            "name": cls._safe_filename(root.get("name"), content_id),
            "files": files,
            "truncated": len(files) >= _MAX_FILES,
        }

    @staticmethod
    def _safe_filename(name, fallback_id: str = "file") -> str:
        value = str(name or "").replace("\\", "/").split("/")[-1].replace("\x00", "").strip()
        if value in ("", ".", ".."):
            value = f"gofile_{(fallback_id or 'file')[:8]}"
        return value[:240]

    @staticmethod
    def _is_storage_url(url: str) -> bool:
        try:
            parsed = urlsplit(str(url))
            port = parsed.port
        except (TypeError, ValueError):
            return False
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme.lower() == "https"
            and port in (None, 443)
            and not parsed.username
            and not parsed.password
            and bool(re.fullmatch(r"store-[a-z0-9-]+\.gofile\.io", host))
        )

    @classmethod
    def download_file(
        cls,
        entry: dict,
        destination: Path,
        max_bytes: int,
        progress: Callable[[int, int], None] | None = None,
        content_id: str = "",
    ):
        """Descarga a `.part`, verifica el tamaño y publica el archivo al finalizar."""
        destination = Path(destination)
        expected_size = max(0, int(entry.get("size") or 0))
        if expected_size and expected_size > max_bytes:
            raise GoFileDownloadError("El archivo supera el límite de tamaño configurado para GoFile.")
        link = entry.get("link")
        if not link or not cls._is_storage_url(link):
            raise GoFileDownloadError("GoFile no proporcionó un enlace de almacenamiento válido.")

        token = cls._get_guest_token()
        headers = {
            "Cookie": f"accountToken={token}",
            "User-Agent": _USER_AGENT,
            "Referer": f"https://gofile.io/d/{content_id}" if content_id else "https://gofile.io/",
        }
        partial = destination.with_name(destination.name + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = 0
        try:
            with requests.get(
                link,
                headers=headers,
                stream=True,
                timeout=(15, 90),
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                final_url = getattr(response, "url", link)
                if final_url and not cls._is_storage_url(final_url):
                    raise GoFileDownloadError("GoFile redirigió a un host de descarga no permitido.")
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "text/html" in content_type:
                    raise GoFileDownloadError("GoFile devolvió una página web en lugar del archivo.")
                try:
                    content_length = max(0, int(response.headers.get("Content-Length") or 0))
                except (TypeError, ValueError):
                    content_length = 0
                if content_length > max_bytes:
                    raise GoFileDownloadError("El archivo supera el límite de tamaño configurado para GoFile.")

                with partial.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        if current == 0 and chunk.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                            raise GoFileDownloadError("GoFile devolvió una página web en lugar del archivo.")
                        current += len(chunk)
                        if current > max_bytes:
                            raise GoFileDownloadError("La descarga superó el límite de tamaño configurado.")
                        output.write(chunk)
                        if progress:
                            try:
                                progress(current, content_length or expected_size)
                            except Exception:
                                logger.debug("No se pudo actualizar el progreso de GoFile", exc_info=True)
            if current == 0:
                raise GoFileDownloadError("GoFile no entregó datos para este archivo.")
            if expected_size and current != expected_size:
                raise GoFileDownloadError(
                    f"La descarga quedó incompleta ({current} de {expected_size} bytes). Vuelve a intentarlo."
                )
            partial.replace(destination)
            return destination, current
        except GoFileDownloadError:
            partial.unlink(missing_ok=True)
            raise
        except requests.RequestException as error:
            partial.unlink(missing_ok=True)
            raise GoFileDownloadError(f"Falló la transferencia desde GoFile: {error}") from error
        except OSError as error:
            partial.unlink(missing_ok=True)
            raise GoFileDownloadError(f"No pude guardar el archivo en el hosting: {error}") from error
        except Exception:
            partial.unlink(missing_ok=True)
            raise
