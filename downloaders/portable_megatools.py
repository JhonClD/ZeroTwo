"""Fetch a pinned official static Megatools build into the project directory."""
from __future__ import annotations

import hashlib
import os
import platform
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path


VERSION = "1.11.5.20250706"
OFFICIAL_BUILDS = "https://xff.cz/megatools/builds/builds"
MAX_ARCHIVE_SIZE = 12 * 1024 * 1024
MAX_BINARY_SIZE = 24 * 1024 * 1024
_INSTALL_LOCK = threading.Lock()

# SHA-256 pins for the official release archives and their signed-manifest binaries.
_BUILDS = {
    "x86_64": {
        "asset": f"megatools-{VERSION}-linux-x86_64.tar.gz",
        "archive_sha256": "f6f6f22cb1d3c166c88d85eb669acfe7741d9ce28f7fb94693980bd37894832a",
        "binary_sha256": "7b9fdd85a608166012a4b163b56e95a60b1ff8886c28c3c5ce0980f42cff88be",
        "directory": f"megatools-{VERSION}-linux-x86_64",
    },
    "aarch64": {
        "asset": f"megatools-{VERSION}-linux-aarch64.tar.gz",
        "archive_sha256": "6addb8609392e2ad1f1894674b996a67f4a4ff5ca8209de1b027aba5515b6a18",
        "binary_sha256": "c7d713847c5dfa4ea846455a9cdd22839602a9488ee719b7c6ade6d5c454aa4c",
        "directory": f"megatools-{VERSION}-linux-aarch64",
    },
}


class PortableMegatoolsError(RuntimeError):
    """Portable Megatools could not be installed or used."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_megatools() -> Path:
    """Return a verified local `megatools` binary, downloading it if needed."""
    arch = platform.machine().lower()
    if arch in {"amd64", "x64"}:
        arch = "x86_64"
    elif arch in {"arm64", "armv8l"}:
        arch = "aarch64"
    build = _BUILDS.get(arch)
    if build is None:
        raise PortableMegatoolsError(
            f"No hay build portable de Megatools configurado para la arquitectura {arch}."
        )

    project_root = Path(__file__).resolve().parents[1]
    install_dir = project_root / ".runtime" / f"megatools-{VERSION}-{arch}"
    binary_path = install_dir / "megatools"
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
                f"{OFFICIAL_BUILDS}/{build['asset']}",
                headers={"User-Agent": "ZeroTwo-Megatools-bootstrap/1.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_ARCHIVE_SIZE:
                    raise PortableMegatoolsError("El paquete de Megatools excede el tamaño esperado.")
                with tempfile.NamedTemporaryFile(
                    prefix="megatools-", suffix=".tar.gz", dir=install_dir, delete=False
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
                            raise PortableMegatoolsError("El paquete de Megatools excede el tamaño esperado.")
                        digest.update(chunk)
                        archive.write(chunk)
            if digest.hexdigest() != build["archive_sha256"]:
                raise PortableMegatoolsError("La verificación SHA-256 del paquete de Megatools falló.")

            expected_member = f"{build['directory']}/megatools"
            with tarfile.open(archive_path, mode="r:gz") as package:
                try:
                    member = package.getmember(expected_member)
                except KeyError as error:
                    raise PortableMegatoolsError("El paquete oficial no contiene el binario esperado.") from error
                if not member.isfile() or member.size > MAX_BINARY_SIZE:
                    raise PortableMegatoolsError("El binario del paquete no es válido.")
                source = package.extractfile(member)
                if source is None:
                    raise PortableMegatoolsError("No se pudo leer el binario de Megatools.")
                with source, tempfile.NamedTemporaryFile(
                    prefix="megatools-", dir=install_dir, delete=False
                ) as output:
                    temporary_binary = Path(output.name)
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        output.write(chunk)

                if digest.hexdigest() != build["binary_sha256"]:
                    raise PortableMegatoolsError("La verificación SHA-256 del binario falló.")

                # Keep the upstream license next to the downloaded executable.
                try:
                    license_member = package.getmember(f"{build['directory']}/LICENSE")
                    license_source = package.extractfile(license_member)
                    if license_source is not None:
                        with license_source:
                            (install_dir / "LICENSE").write_bytes(license_source.read())
                except KeyError:
                    pass

            temporary_binary.chmod(0o755)
            temporary_binary.replace(binary_path)
            return binary_path
        except PortableMegatoolsError:
            raise
        except Exception as error:
            raise PortableMegatoolsError(
                f"No se pudo instalar Megatools portable: {error}"
            ) from error
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)
            if temporary_binary is not None:
                temporary_binary.unlink(missing_ok=True)
