"""Descargas BitTorrent con aria2c del sistema o una copia portable para Linux."""

import shutil
import subprocess
from pathlib import Path

from downloaders.portable_aria2 import ensure_aria2c


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
    def download(source, output_dir: Path, timeout=None):
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
