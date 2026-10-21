"""Descarga archivos desde enlaces públicos compartidos de Drime Cloud."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

_API_BASE = "https://app.drime.cloud/api/v1"
_PUBLIC_HOST = "app.drime.cloud"
_SHARE_PATH_RE = re.compile(r"^/drive/(?:s|shares)/([A-Za-z0-9_-]{8,80})/?$")
_HASH_RE = re.compile(r"^[A-Za-z0-9_-]{4,80}$")
_HEADERS = {
    "Accept": "application/json, */*",
    "User-Agent": "Mozilla/5.0 (compatible; ZeroTwoBot/1.0)",
}


def _request_headers(referer: str) -> dict[str, str]:
    """Añade el token oficial opcional sin guardarlo en el código."""
    headers = {**_HEADERS, "Referer": referer}
    token = os.getenv("DRIME_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_cloudflare_challenge(response) -> bool:
    return str(response.headers.get("cf-mitigated", "")).lower() == "challenge"


def _cloudflare_error() -> DrimeDownloadError:
    return DrimeDownloadError(
        "Cloudflare está bloqueando las solicitudes del hosting del bot. "
        "El token API no evita ese desafío; pide a Drime que autorice la IP saliente del hosting "
        "o usa el botón Download del enlace en el navegador."
    )


class DrimeDownloadError(RuntimeError):
    """Error legible al consultar o descargar un enlace de Drime."""


class DrimeDownloader:
    """Cliente de enlaces públicos Drime con soporte opcional para API token."""

    @staticmethod
    def is_drime_url(url: str) -> bool:
        return DrimeDownloader.share_hash(url) is not None

    @staticmethod
    def share_hash(url: str) -> str | None:
        try:
            parsed = urlparse(url.strip())
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != _PUBLIC_HOST:
            return None
        match = _SHARE_PATH_RE.fullmatch(parsed.path)
        return match.group(1) if match else None

    @staticmethod
    def list_shared_files(url: str, max_pages: int = 20) -> dict:
        """Obtiene metadata de los archivos de una carpeta compartida pública."""
        share_hash = DrimeDownloader.share_hash(url)
        if not share_hash:
            raise DrimeDownloadError("El enlace no parece un share público válido de app.drime.cloud.")

        referer = f"https://{_PUBLIC_HOST}/drive/s/{share_hash}"
        link = None
        files = []
        pages_to_read = 1
        for page in range(1, min(max_pages, 20) + 1):
            try:
                response = requests.get(
                    f"{_API_BASE}/shareable-links/{share_hash}",
                    params={"withEntries": "true", "page": page, "order": "updated_at:desc"},
                    headers=_request_headers(referer),
                    timeout=(15, 45),
                )
            except requests.RequestException as error:
                raise DrimeDownloadError(f"No se pudo conectar con Drime: {error}") from error

            if _is_cloudflare_challenge(response):
                raise _cloudflare_error()
            if response.status_code in {401, 403, 404, 410, 423}:
                raise DrimeDownloadError(
                    "El enlace Drime está privado, vencido, protegido con contraseña o no permite acceder. "
                    "Verifica que el enlace sea público y tenga habilitada la descarga."
                )
            if response.status_code != 200:
                raise DrimeDownloadError(f"Drime respondió HTTP {response.status_code} al consultar el enlace.")
            try:
                data = response.json()
            except ValueError as error:
                raise DrimeDownloadError("Drime no devolvió metadata JSON para ese enlace.") from error

            current_link = data.get("link")
            if not isinstance(current_link, dict):
                raise DrimeDownloadError("Drime no encontró el enlace compartido.")
            if link is None:
                link = current_link
                if current_link.get("allow_download") is False:
                    raise DrimeDownloadError("El propietario desactivó la descarga para este enlace de Drime.")
                direct_entry = current_link.get("entry")
                if (
                    isinstance(direct_entry, dict)
                    and direct_entry.get("type") != "folder"
                    and direct_entry.get("hash")
                    and direct_entry.get("name")
                ):
                    files.append(direct_entry)
                try:
                    link_id = int(current_link["id"])
                except (KeyError, TypeError, ValueError) as error:
                    raise DrimeDownloadError("Drime no entregó un identificador válido para el enlace.") from error

            children = data.get("folderChildren") or data.get("entries") or []
            if isinstance(children, dict):
                page_data = children.get("data", [])
                try:
                    pages_to_read = max(pages_to_read, int(children.get("last_page", 1) or 1))
                except (TypeError, ValueError):
                    pass
            elif isinstance(children, list):
                page_data = children
            else:
                page_data = []
            if isinstance(page_data, list):
                files.extend(
                    entry for entry in page_data
                    if isinstance(entry, dict) and entry.get("hash") and entry.get("name")
                )
            if page >= pages_to_read:
                break

        if not files:
            raise DrimeDownloadError("No encontré archivos descargables en ese enlace compartido de Drime.")
        for entry in files:
            if not _HASH_RE.fullmatch(str(entry.get("hash", ""))):
                raise DrimeDownloadError("Drime entregó un identificador de archivo no válido.")
        return {"share_hash": share_hash, "share_id": link_id, "files": files}

    @staticmethod
    def download_file(
        share_hash: str,
        share_id: int,
        entry: dict,
        destination: str | Path,
        max_bytes: int,
        progress=None,
    ) -> tuple[Path, int]:
        """Descarga un archivo mediante el permiso del enlace compartido."""
        entry_hash = str(entry.get("hash", ""))
        if not _HASH_RE.fullmatch(entry_hash):
            raise DrimeDownloadError("El identificador de archivo de Drime no es válido.")
        expected_size = int(entry.get("file_size") or 0)
        if expected_size and expected_size > max_bytes:
            raise DrimeDownloadError(
                f"El archivo supera el límite del hosting ({max_bytes // (1024 * 1024)} MB)."
            )

        path = Path(destination)
        part_path = path.with_name(path.name + ".part")
        referer = f"https://{_PUBLIC_HOST}/drive/s/{share_hash}"
        response = None
        try:
            response = requests.get(
                f"{_API_BASE}/file-entries/download/{entry_hash}",
                params={"shareable_link": share_id, "password": "null"},
                headers=_request_headers(referer),
                stream=True,
                allow_redirects=True,
                timeout=(20, 180),
            )
            if _is_cloudflare_challenge(response):
                raise _cloudflare_error()
            if response.status_code in {401, 403, 404, 410, 423}:
                raise DrimeDownloadError(
                    "Drime rechazó la descarga. Comprueba que el enlace siga público y permita descargar."
                )
            if response.status_code != 200:
                raise DrimeDownloadError(f"Drime respondió HTTP {response.status_code} al descargar el archivo.")

            try:
                content_length = int(response.headers.get("Content-Length", "0") or 0)
            except ValueError:
                content_length = 0
            if content_length and content_length > max_bytes:
                raise DrimeDownloadError(
                    f"El servidor indica que el archivo supera el límite de {max_bytes // (1024 * 1024)} MB."
                )
            content_type = str(response.headers.get("Content-Type", "")).lower()
            chunks = response.iter_content(chunk_size=1024 * 1024)
            first_chunk = next(chunks, b"")
            prefix = first_chunk[:2048].lstrip().lower()
            if "text/html" in content_type or prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
                raise DrimeDownloadError("Drime devolvió una página web en vez del archivo.")
            if not first_chunk:
                raise DrimeDownloadError("Drime devolvió un archivo vacío.")

            path.parent.mkdir(parents=True, exist_ok=True)
            total = len(first_chunk)
            last_reported = 0.0
            with part_path.open("wb") as output:
                output.write(first_chunk)
                if progress:
                    progress(total, expected_size or content_length)
                for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise DrimeDownloadError(
                            f"La descarga alcanzó el límite de {max_bytes // (1024 * 1024)} MB del hosting."
                        )
                    output.write(chunk)
                    now = time.monotonic()
                    if progress and (now - last_reported >= 2 or (expected_size and total >= expected_size)):
                        progress(total, expected_size or content_length)
                        last_reported = now

            if expected_size and total != expected_size:
                raise DrimeDownloadError(
                    f"Descarga incompleta: se recibieron {total} de {expected_size} bytes."
                )
            if total == 0:
                raise DrimeDownloadError("Drime devolvió un archivo vacío.")
            part_path.replace(path)
            return path, total
        except DrimeDownloadError:
            part_path.unlink(missing_ok=True)
            raise
        except requests.RequestException as error:
            part_path.unlink(missing_ok=True)
            raise DrimeDownloadError(f"Falló la conexión al descargar desde Drime: {error}") from error
        except OSError as error:
            part_path.unlink(missing_ok=True)
            raise DrimeDownloadError(f"No se pudo guardar en el hosting: {error}") from error
        finally:
            if response is not None:
                response.close()
