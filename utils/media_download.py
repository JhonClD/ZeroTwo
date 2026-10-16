"""Descarga HTTP de medios con reintentos y validación de integridad."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import requests


class MediaDownloadError(RuntimeError):
    """Una URL multimedia devolvió un error o una carga no válida."""


_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        return min(max(float(retry_after), 0), 8) if retry_after else min(2 ** attempt, 6)
    except ValueError:
        return min(2 ** attempt, 6)


def download_file(
    url: str,
    destination: str | Path,
    timeout: Any = (15, 120),
    retries: int = 3,
) -> int:
    """Descarga y valida un medio, reintentando solo errores transitorios.

    Escribe primero a un archivo `.part` y lo renombra al terminar para que un
    proceso interrumpido nunca deje un archivo parcial con nombre definitivo.
    """
    path = Path(destination)
    part_path = path.with_name(f"{path.name}.part")
    attempts = max(1, int(retries))
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ZeroTwoBot/1.0)",
        "Accept": "*/*",
    }
    last_error: Exception | None = None

    for attempt in range(attempts):
        response = None
        try:
            response = requests.get(
                url,
                stream=True,
                timeout=timeout,
                headers=headers,
                allow_redirects=True,
            )
            if response.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                delay = _retry_delay(response, attempt)
                response.close()
                response = None
                time.sleep(delay)
                continue
            response.raise_for_status()

            content_type = str(response.headers.get("Content-Type", "")).lower()
            chunks = response.iter_content(chunk_size=64 * 1024)
            first = next(chunks, b"")
            prefix = first[:2048].lstrip().lower()
            if "text/html" in content_type or prefix.startswith(
                (b"<!doctype html", b"<html", b"<head", b"<body")
            ):
                raise MediaDownloadError(
                    "El servidor devolvió una página HTML en vez del archivo multimedia."
                )
            if not first:
                raise MediaDownloadError("La descarga devolvió un archivo vacío.")

            path.parent.mkdir(parents=True, exist_ok=True)
            size = len(first)
            with part_path.open("wb") as output:
                output.write(first)
                for chunk in chunks:
                    if chunk:
                        output.write(chunk)
                        size += len(chunk)

            if size < 1024:
                raise MediaDownloadError(
                    f"La descarga es demasiado pequeña ({size} bytes), parece incompleta."
                )

            expected = response.headers.get("Content-Length")
            content_encoding = str(response.headers.get("Content-Encoding", "identity")).lower()
            transfer_encoding = str(response.headers.get("Transfer-Encoding", "")).lower()
            if expected and content_encoding in {"", "identity"} and "chunked" not in transfer_encoding:
                try:
                    if size != int(expected):
                        raise MediaDownloadError(
                            f"Descarga incompleta: se recibieron {size} de {expected} bytes."
                        )
                except ValueError:
                    pass

            part_path.replace(path)
            return size
        except MediaDownloadError:
            part_path.unlink(missing_ok=True)
            raise
        except requests.RequestException as error:
            last_error = error
            part_path.unlink(missing_ok=True)
            status = getattr(getattr(error, "response", None), "status_code", None)
            retryable = status is None or status in _RETRYABLE_STATUS
            if attempt < attempts - 1 and retryable:
                time.sleep(_retry_delay(response, attempt))
                continue
            if status:
                raise MediaDownloadError(
                    f"El servidor de descarga respondió HTTP {status}."
                ) from error
            raise MediaDownloadError(f"No se pudo descargar el archivo: {error}") from error
        except OSError as error:
            part_path.unlink(missing_ok=True)
            raise MediaDownloadError(
                f"No se pudo guardar la descarga en el hosting: {error}"
            ) from error
        finally:
            if response is not None:
                response.close()

    part_path.unlink(missing_ok=True)
    if last_error:
        raise MediaDownloadError(f"No se pudo completar la descarga: {last_error}") from last_error
    raise MediaDownloadError("No se pudo completar la descarga.")
