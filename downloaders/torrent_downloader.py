"""Descargas BitTorrent con aria2c del sistema o una copia portable para Linux."""

import ipaddress
import socket
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from downloaders.portable_aria2 import ensure_aria2c

_MAX_TORRENT_BYTES = 10 * 1024 * 1024
_MAX_REDIRECTS = 5


class TorrentDownloader:
    """Wrapper seguro para aria2c sin ejecutar shell."""

    @staticmethod
    def _aria2_binary():
        system_binary = shutil.which("aria2c")
        if system_binary:
            return system_binary
        return str(ensure_aria2c())

    @staticmethod
    def _validate_public_url(url):
        """Solo permite HTTP(S) en hosts públicos, evitando destinos locales."""
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("El enlace debe ser una URL HTTP o HTTPS pública.")
        if parsed.username or parsed.password:
            raise ValueError("No se permiten credenciales dentro del enlace.")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as error:
            raise ValueError("No se pudo resolver el servidor del enlace .torrent.") from error
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("El enlace debe apuntar a un servidor público, no a una red privada.")
        return parsed

    @staticmethod
    def _download_torrent_url(url, destination):
        parsed = TorrentDownloader._validate_public_url(url)
        if not parsed.path.lower().endswith(".torrent"):
            raise ValueError("La URL debe apuntar directamente a un archivo .torrent.")

        current_url = url
        response = None
        try:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                TorrentDownloader._validate_public_url(current_url)
                response = requests.get(
                    current_url,
                    stream=True,
                    timeout=(10, 30),
                    allow_redirects=False,
                    headers={"User-Agent": "ZeroTwo-Torrent/1.0"},
                )
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    response.close()
                    response = None
                    if not location or redirect_count >= _MAX_REDIRECTS:
                        raise ValueError("El servidor devolvió demasiadas redirecciones o una redirección inválida.")
                    current_url = urljoin(current_url, location)
                    redirected = TorrentDownloader._validate_public_url(current_url)
                    if not redirected.path.lower().endswith(".torrent"):
                        raise ValueError("La redirección no apunta a un archivo .torrent.")
                    continue

                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > _MAX_TORRENT_BYTES:
                    raise ValueError("El archivo .torrent supera el límite de 10 MB.")
                partial = destination.with_suffix(destination.suffix + ".part")
                total = 0
                try:
                    with partial.open("wb") as output:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > _MAX_TORRENT_BYTES:
                                raise ValueError("El archivo .torrent supera el límite de 10 MB.")
                            output.write(chunk)
                    data = partial.read_bytes()
                    if not data.startswith(b"d") or b"4:info" not in data:
                        raise ValueError("La URL no devolvió un archivo .torrent válido.")
                    partial.replace(destination)
                finally:
                    partial.unlink(missing_ok=True)
                return destination
            raise ValueError("No se pudo seguir la redirección del enlace .torrent.")
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def available():
        try:
            TorrentDownloader._aria2_binary()
            return True
        except Exception:
            return False

    @staticmethod
    def download(source, output_dir: Path, timeout=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        source_path = source
        if isinstance(source, str) and source.lower().startswith(("http://", "https://")):
            try:
                source_path = str(TorrentDownloader._download_torrent_url(source, output_dir / "source.torrent"))
            except (ValueError, requests.RequestException, OSError) as error:
                return False, [], f"No se pudo obtener el archivo .torrent: {error}"

        try:
            aria2_binary = TorrentDownloader._aria2_binary()
        except Exception as error:
            return False, [], (
                "No se encontró aria2c y no se pudo preparar el ejecutable portable. "
                "El hosting necesita acceso HTTPS a GitHub y permiso para ejecutar "
                f"archivos en .runtime/: {error}"
            )

        command = [
            aria2_binary, "--dir", str(output_dir), "--continue=true",
            "--seed-time=0", "--follow-torrent=true", "--bt-enable-lpd=true",
            "--enable-dht=true", "--summary-interval=5", "--console-log-level=warn",
            "--file-allocation=none", str(source_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, [], "La descarga torrent superó el tiempo límite."
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            return False, [], detail or "aria2c terminó con error."
        files = sorted(
            (p for p in output_dir.rglob("*") if p.is_file() and not p.name.endswith((".aria2", ".torrent"))),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        return bool(files), files, "" if files else "El torrent terminó sin archivos descargados."
