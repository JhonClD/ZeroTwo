"""Descargas BitTorrent mediante aria2c, compatible con Termux."""

import shutil
import subprocess
from pathlib import Path


class TorrentDownloader:
    """Wrapper seguro para aria2c sin ejecutar shell."""

    @staticmethod
    def available():
        return shutil.which("aria2c") is not None

    @staticmethod
    def download(source, output_dir: Path, timeout=None):
        if not TorrentDownloader.available():
            return False, [], "No se encontró aria2c. Instálalo con: pkg install aria2"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "aria2c", "--dir", str(output_dir), "--continue=true",
            "--seed-time=0", "--follow-torrent=true", "--bt-enable-lpd=true",
            "--enable-dht=true", "--summary-interval=5", "--console-log-level=warn",
            "--file-allocation=none", str(source),
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
