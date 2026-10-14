"""Basic HTTP media download and validation helpers."""
from pathlib import Path
from typing import Any

import requests


class MediaDownloadError(RuntimeError):
    """A media URL returned an error or an invalid payload."""


def download_file(url: str, destination: str | Path, timeout: Any = (15, 120)) -> int:
    """Download a media file and reject HTTP/HTML/empty responses."""
    path = Path(destination)
    response = None
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        chunks = response.iter_content(chunk_size=64 * 1024)
        first = next(chunks, b"")
        content_type = str(response.headers.get("Content-Type", "")).lower()
        prefix = first[:2048].lstrip().lower()
        if "text/html" in content_type or prefix.startswith(
            (b"<!doctype html", b"<html", b"<head", b"<body")
        ):
            raise MediaDownloadError(
                "El servidor devolvió una página HTML en vez del archivo multimedia"
            )
        if not first:
            raise MediaDownloadError("La descarga devolvió un archivo vacío")

        path.parent.mkdir(parents=True, exist_ok=True)
        size = len(first)
        with path.open("wb") as output:
            output.write(first)
            for chunk in chunks:
                if chunk:
                    output.write(chunk)
                    size += len(chunk)
        if size < 1024:
            raise MediaDownloadError(
                f"La descarga es demasiado pequeña ({size} bytes), parece incompleta"
            )
        return size
    except MediaDownloadError:
        path.unlink(missing_ok=True)
        raise
    except requests.RequestException as error:
        path.unlink(missing_ok=True)
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status:
            raise MediaDownloadError(f"El servidor de descarga respondió HTTP {status}") from error
        raise MediaDownloadError(f"No se pudo descargar el archivo: {error}") from error
    except OSError as error:
        path.unlink(missing_ok=True)
        raise MediaDownloadError(f"No se pudo guardar la descarga en el hosting: {error}") from error
    finally:
        if response is not None:
            response.close()
