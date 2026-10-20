"""Descargas BitTorrent con aria2c y progreso legible para el bot."""

import ipaddress
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

from downloaders.portable_aria2 import ensure_aria2c

_MAX_TORRENT_BYTES = 10 * 1024 * 1024
_MAX_REDIRECTS = 5
_SIZE_TOKEN_RE = re.compile(r"(?P<done>[\d.]+\s*[KMGT]?i?B)/(?P<total>[\d.]+\s*[KMGT]?i?B)\s*\((?P<pct>\d+(?:\.\d+)?)%\)", re.IGNORECASE)
_SIZE_VALUE_RE = re.compile(r"^\s*(?P<value>[\d.]+)\s*(?P<unit>[KMGT]?i?B)?\s*$", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _decode_bencode(data):
    """Decodifica un metainfo bencode pequeño sin una dependencia adicional."""
    def parse(index):
        if index >= len(data):
            raise ValueError("bencode truncado")
        marker = data[index:index + 1]
        if marker == b"i":
            end = data.index(b"e", index)
            return int(data[index + 1:end]), end + 1
        if marker == b"l":
            values = []
            index += 1
            while data[index:index + 1] != b"e":
                value, index = parse(index)
                values.append(value)
            return values, index + 1
        if marker == b"d":
            values = {}
            index += 1
            while data[index:index + 1] != b"e":
                key, index = parse(index)
                value, index = parse(index)
                values[key] = value
            return values, index + 1
        colon = data.index(b":", index)
        length = int(data[index:colon])
        start = colon + 1
        end = start + length
        if length < 0 or end > len(data):
            raise ValueError("cadena bencode inválida")
        return data[start:end], end

    value, end = parse(0)
    if end != len(data):
        raise ValueError("datos sobrantes en bencode")
    return value


def _torrent_metadata(source):
    """Obtiene nombre, tamaño total y cantidad de archivos si hay metainfo disponible."""
    metadata = {"name": "Torrent", "total_size": 0, "total_files": 0}
    try:
        if isinstance(source, str) and source.lower().startswith("magnet:"):
            query = parse_qs(urlsplit(source).query)
            metadata["name"] = (query.get("dn") or ["Torrent"])[0]
            return metadata
        path = Path(source)
        if not path.is_file() or path.stat().st_size > _MAX_TORRENT_BYTES:
            return metadata
        torrent = _decode_bencode(path.read_bytes())
        info = torrent.get(b"info", {}) if isinstance(torrent, dict) else {}
        if not isinstance(info, dict):
            return metadata
        raw_name = info.get(b"name.utf-8", info.get(b"name", b"Torrent"))
        metadata["name"] = raw_name.decode("utf-8", errors="replace") if isinstance(raw_name, bytes) else str(raw_name)
        entries = info.get(b"files")
        if isinstance(entries, list):
            metadata["total_files"] = len(entries)
            metadata["total_size"] = sum(max(0, item.get(b"length", 0)) for item in entries if isinstance(item, dict))
        elif isinstance(info.get(b"length"), int):
            metadata["total_files"] = 1
            metadata["total_size"] = max(0, info[b"length"])
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        pass
    return metadata


def _parse_aria2_progress(output):
    """Extrae bytes y porcentaje de la línea de estado de aria2, si está presente."""
    match = _SIZE_TOKEN_RE.search(_ANSI_RE.sub("", output))
    if not match:
        return None

    def to_bytes(value):
        parsed = _SIZE_VALUE_RE.match(value)
        if not parsed:
            return 0
        number = float(parsed.group("value"))
        unit = (parsed.group("unit") or "B").upper().replace("IB", "B")
        exponent = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4}.get(unit, 0)
        return int(number * (1024 ** exponent))

    return {
        "completed_size": to_bytes(match.group("done")),
        "total_size": to_bytes(match.group("total")),
        "percent": float(match.group("pct")),
    }


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
    def download(source, output_dir: Path, timeout=None, progress_callback=None):
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

        metadata = _torrent_metadata(source_path)
        if isinstance(source, str) and source.lower().startswith("magnet:"):
            metadata = _torrent_metadata(source)
        command = [
            aria2_binary, "--dir", str(output_dir), "--continue=true",
            "--seed-time=0", "--follow-torrent=true", "--bt-enable-lpd=true",
            "--enable-dht=true", "--summary-interval=5", "--show-console-readout=true",
            "--console-log-level=notice", "--file-allocation=none", str(source_path),
        ]
        start = time.monotonic()
        output_lines = []
        updates = queue.Queue()
        sentinel = object()
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as error:
            return False, [], f"No se pudo iniciar aria2c: {error}"

        def read_output():
            try:
                for line in process.stdout:
                    updates.put(line)
            finally:
                updates.put(sentinel)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        completed_size = 0
        reported_total = int(metadata.get("total_size") or 0)
        reported_percent = 0.0
        last_report = 0.0
        timed_out = False

        def report_progress(force=False):
            nonlocal last_report
            if not progress_callback:
                return
            now = time.monotonic()
            if not force and now - last_report < 2:
                return
            current = dict(metadata)
            current.update({
                "completed_size": completed_size,
                "total_size": reported_total,
                "percent": reported_percent,
                "elapsed": int(now - start),
                "current_files": sum(
                    1 for path in output_dir.rglob("*")
                    if path.is_file() and not path.name.endswith((".aria2", ".torrent"))
                ),
            })
            try:
                progress_callback(current)
            except Exception:
                pass
            last_report = now

        report_progress(force=True)
        done_reading = False
        while not done_reading:
            if timeout is not None and time.monotonic() - start > timeout:
                timed_out = True
                process.kill()
                break
            try:
                line = updates.get(timeout=0.5)
            except queue.Empty:
                report_progress()
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is sentinel:
                done_reading = True
                continue
            output_lines.append(line)
            if len(output_lines) > 200:
                output_lines = output_lines[-100:]
            parsed = _parse_aria2_progress(line)
            if parsed:
                completed_size = parsed["completed_size"]
                reported_total = parsed["total_size"] or reported_total
                reported_percent = parsed["percent"]
                report_progress(force=True)

        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
        reader.join(timeout=1)
        if timed_out:
            return False, [], "La descarga torrent superó el tiempo límite."
        if return_code != 0:
            detail = "".join(output_lines).strip()[-1200:]
            return False, [], detail or "aria2c terminó con error."
        files = sorted(
            (p for p in output_dir.rglob("*") if p.is_file() and not p.name.endswith((".aria2", ".torrent"))),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        reported_total = reported_total or sum(path.stat().st_size for path in files)
        reported_percent = 100.0
        if files:
            metadata["total_files"] = metadata.get("total_files") or len(files)
            completed_size = reported_total
            report_progress(force=True)
        return bool(files), files, "" if files else "El torrent terminó sin archivos descargados."
