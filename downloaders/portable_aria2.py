"""Descarga aria2c estático fijado por versión y SHA-256 para Linux sin root."""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.37.0"
RELEASE_URL = f"https://github.com/abcfy2/aria2-static-build/releases/download/{VERSION}"
MAX_ARCHIVE_SIZE = 8 * 1024 * 1024
MAX_BINARY_SIZE = 20 * 1024 * 1024
_INSTALL_LOCK = threading.Lock()

# SHA-256 fijados de los artefactos del release; soporta Linux x86_64 y ARM.
_BUILDS = {
    "x86_64": {
        "asset": "aria2-x86_64-linux-musl_static.zip",
        "sha256": "e0a09b12ef67f35f8a8e4fdddbec851d235b7c31da549d0578bff459032b499a",
        "binary_sha256": "80e577dc58348b96da46dd12d326bc99794b5021be395a3e890f2d67c8790c22",
    },
    "aarch64": {
        "asset": "aria2-aarch64-linux-musl_static.zip",
        "sha256": "0c681a89a40e0f82d1f5137608e86257eb0af201459c002941ea098f2b8c26b6",
        "binary_sha256": "99a057bd383a28f1d5fab6e8cc5f6f3ed4172f5e65c59548242e965454d654c1",
    },
    "armv7": {
        "asset": "aria2-armv7-linux-musleabihf_static.zip",
        "sha256": "f165909861cc70bfa59eca5e70e5d92064bd84c35223814f43492713c4e0c7ae",
        "binary_sha256": "6ff7f2adea9a83ef97e5b7f2b44d0b27807c2c3f2690969ac5a0ced76df0248b",
    },
}


class PortableAria2Error(RuntimeError):
    """aria2c portable no se pudo instalar o validar."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_arch() -> str:
    arch = platform.machine().lower()
    if arch in {"amd64", "x64"}:
        return "x86_64"
    if arch in {"arm64", "armv8l"}:
        return "aarch64" if arch == "arm64" else "armv7"
    if arch in {"armv7l", "armv7"}:
        return "armv7"
    return arch


def ensure_aria2c() -> Path:
    """Devuelve un aria2c verificado en .runtime; lo instala si aún no existe."""
    arch = _normalise_arch()
    build = _BUILDS.get(arch)
    if build is None:
        raise PortableAria2Error(
            f"No hay aria2c portable configurado para la arquitectura Linux {arch}."
        )
    if platform.system().lower() != "linux":
        raise PortableAria2Error("El fallback portable de aria2c solo está preparado para Linux.")

    root = Path(__file__).resolve().parents[1]
    install_dir = root / ".runtime" / f"aria2-{VERSION}-{arch}"
    binary_path = install_dir / "aria2c"
    if binary_path.is_file() and os.access(binary_path, os.X_OK):
        if _sha256(binary_path) == build["binary_sha256"]:
            return binary_path

    with _INSTALL_LOCK:
        if binary_path.is_file() and os.access(binary_path, os.X_OK):
            if _sha256(binary_path) == build["binary_sha256"]:
                return binary_path

        install_dir.mkdir(parents=True, exist_ok=True)
        archive_path = None
        temporary_binary = None
        try:
            request = urllib.request.Request(
                f"{RELEASE_URL}/{build['asset']}",
                headers={"User-Agent": "ZeroTwo-aria2-bootstrap/1.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_ARCHIVE_SIZE:
                    raise PortableAria2Error("El paquete de aria2c excede el tamaño esperado.")
                with tempfile.NamedTemporaryFile(
                    prefix="aria2-", suffix=".zip", dir=install_dir, delete=False
                ) as archive:
                    archive_path = Path(archive.name)
                    digest = hashlib.sha256()
                    total = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_ARCHIVE_SIZE:
                            raise PortableAria2Error("El paquete de aria2c excede el tamaño esperado.")
                        digest.update(chunk)
                        archive.write(chunk)
            if digest.hexdigest() != build["sha256"]:
                raise PortableAria2Error("La verificación SHA-256 del paquete aria2c falló.")

            with zipfile.ZipFile(archive_path) as package:
                try:
                    member = package.getinfo("aria2c")
                except KeyError as error:
                    raise PortableAria2Error("El paquete no contiene el ejecutable aria2c esperado.") from error
                if member.is_dir() or member.file_size <= 0 or member.file_size > MAX_BINARY_SIZE:
                    raise PortableAria2Error("El ejecutable aria2c del paquete no es válido.")
                with package.open(member) as source, tempfile.NamedTemporaryFile(
                    prefix="aria2c-", dir=install_dir, delete=False
                ) as output:
                    temporary_binary = Path(output.name)
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        output.write(chunk)

            if _sha256(temporary_binary) != build["binary_sha256"]:
                raise PortableAria2Error("La verificación SHA-256 del ejecutable aria2c falló.")
            temporary_binary.chmod(0o755)
            version = subprocess.run(
                [str(temporary_binary), "--version"],
                capture_output=True, text=True, timeout=15,
            )
            version_text = version.stdout + version.stderr
            if version.returncode != 0 or f"aria2 version {VERSION}" not in version_text or "BitTorrent" not in version_text:
                raise PortableAria2Error("El ejecutable descargado no pasó la comprobación de versión/BitTorrent.")

            temporary_binary.replace(binary_path)
            return binary_path
        except PortableAria2Error:
            raise
        except Exception as error:
            raise PortableAria2Error(f"No se pudo preparar aria2c portable: {error}") from error
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)
            if temporary_binary is not None:
                temporary_binary.unlink(missing_ok=True)
