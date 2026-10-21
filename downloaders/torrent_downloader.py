"""Descargas BitTorrent con aria2c del sistema o una copia portable para Linux."""

import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from downloaders.portable_aria2 import ensure_aria2c
from utils.transfer_status import parse_bytes


_PROGRESS_RE = re.compile(
    r"(?P<current>[\d.]+\s*[KMGT]?i?B)/(?P<total>[\d.]+\s*[KMGT]?i?B)\((?P<pct>\d+)%\)",
    re.IGNORECASE,
)
_SPEED_RE = re.compile(r"DL:(?P<speed>[\d.]+\s*[KMGT]?i?B)", re.IGNORECASE)


def parse_aria2_progress(line: str) -> tuple[int, int, int | None] | None:
    """Extrae bytes actuales, totales y velocidad de una línea de aria2c."""
    match = _PROGRESS_RE.search(line or "")
    if not match:
        return None
    current = parse_bytes(match.group("current"))
    total = parse_bytes(match.group("total"))
    speed_match = _SPEED_RE.search(line)
    speed = parse_bytes(speed_match.group("speed")) if speed_match else None
    if current is None or total is None or total <= 0:
        return None
    return current, total, speed


class TorrentDownloader:
    """Wrapper seguro para aria2c sin ejecutar shell."""

    @staticmethod
    def _aria2_binary():
        system_binary = shutil.which("aria2c")
        if system_binary:
            return system_binary
        return str(ensure_aria2c())

    @staticmethod
    def available():
        try:
            TorrentDownloader._aria2_binary()
            return True
        except Exception:
            return False

    @staticmethod
    def download(source, output_dir: Path, timeout=None, progress_callback=None):
        try:
            aria2_binary = TorrentDownloader._aria2_binary()
        except Exception as error:
            return False, [], (
                "No se encontró aria2c y no se pudo preparar el ejecutable portable. "
                "El hosting necesita acceso HTTPS a GitHub y permiso para ejecutar "
                f"archivos en .runtime/: {error}"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            aria2_binary, "--dir", str(output_dir), "--continue=true",
            "--seed-time=0", "--follow-torrent=true", "--bt-enable-lpd=true",
            "--enable-dht=true", "--summary-interval=1", "--console-log-level=notice",
            "--show-console-readout=true", "--file-allocation=none", str(source),
        ]
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except OSError as error:
            return False, [], f"No pude iniciar aria2c: {error}"

        output_lines: queue.Queue[str | None] = queue.Queue()

        def read_output():
            try:
                for line in process.stdout:
                    output_lines.put(line)
            finally:
                output_lines.put(None)

        reader = threading.Thread(target=read_output, name="aria2-output-reader", daemon=True)
        reader.start()
        started = time.monotonic()
        output_tail: list[str] = []
        stream_closed = False

        while not stream_closed:
            if timeout is not None and time.monotonic() - started >= timeout:
                process.kill()
                process.wait()
                return False, [], "La descarga torrent superó el tiempo límite."
            try:
                line = output_lines.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                stream_closed = True
                continue
            line = line.rstrip()
            if line:
                output_tail.append(line)
                if len(output_tail) > 30:
                    output_tail.pop(0)
                progress = parse_aria2_progress(line)
                if progress and progress_callback:
                    try:
                        progress_callback(*progress)
                    except Exception:
                        pass

        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return False, [], "aria2c no terminó correctamente."

        if return_code != 0:
            detail = "\n".join(output_tail).strip()[-1200:]
            return False, [], detail or "aria2c terminó con error."
        files = sorted(
            (p for p in output_dir.rglob("*") if p.is_file() and not p.name.endswith((".aria2", ".torrent"))),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        return bool(files), files, "" if files else "El torrent terminó sin archivos descargados."
