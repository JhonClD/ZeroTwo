"""Inspección de metadatos RAR y validación de rutas de extracción."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import rarfile


@dataclass(frozen=True)
class ArchiveInfo:
    files: int
    total_bytes: int
    password_required: bool


def safe_member_path(name: str) -> bool:
    """Devuelve False para nombres absolutos o con traversal/sintaxis Windows."""
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(name)
    return not (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part == ".." for part in posix.parts)
    )


def inspect_archive(path: str | Path, password: str | None = None) -> ArchiveInfo:
    """Lee nombres, tamaños y protección sin extraer contenido del archivo."""
    with rarfile.RarFile(str(path)) as archive:
        if password is not None:
            archive.setpassword(password)
        entries = archive.infolist()
        files = []
        password_required = archive.needs_password()
        for entry in entries:
            if not safe_member_path(entry.filename):
                raise ValueError("El archivo contiene una ruta insegura.")
            is_symlink = getattr(entry, "is_symlink", None)
            if callable(is_symlink) and is_symlink():
                raise ValueError("No se permiten enlaces simbólicos dentro del RAR.")
            if not entry.is_dir():
                files.append(entry)
                password_required = password_required or entry.needs_password()
        return ArchiveInfo(
            files=len(files),
            total_bytes=sum(max(0, int(entry.file_size or 0)) for entry in files),
            password_required=bool(password_required),
        )


__all__ = ["ArchiveInfo", "inspect_archive", "safe_member_path"]
