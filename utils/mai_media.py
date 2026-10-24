"""Validación de opciones y construcción segura de comandos para mai_tools."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shlex
from pathlib import Path


ALLOWED_PRESETS = {"ultrafast", "superfast", "veryfast", "fast", "medium"}
_BITRATE_RE = re.compile(r"^[1-9]\d{2,5}(?:k|M)?$")


@dataclass(frozen=True)
class EncodeOptions:
    audio_index: int = 0
    subtitle_index: int = 0
    bitrate: str = "4800k"
    preset: str = "superfast"


def parse_encode_options(text: str, *, burn_subtitles: bool) -> EncodeOptions:
    """Parsea solo -a, -s, -vb y -p; valida antes de pasarlos a FFmpeg."""
    try:
        tokens = shlex.split(text)
    except ValueError as error:
        raise ValueError("No pude interpretar las opciones.") from error

    allowed = {"-a", "-vb", "-p"}
    if burn_subtitles:
        allowed.add("-s")
    values: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        option = tokens[index]
        if option not in allowed:
            raise ValueError(f"Opción no admitida: {option}.")
        if option in values:
            raise ValueError(f"La opción {option} no se puede repetir.")
        if index + 1 >= len(tokens):
            raise ValueError(f"Falta el valor de {option}.")
        value = tokens[index + 1]
        if value.startswith("-"):
            raise ValueError(f"Valor no válido para {option}.")
        values[option] = value
        index += 2

    def ordinal(option: str) -> int:
        value = values.get(option, "0")
        if not value.isdigit() or int(value) > 50:
            raise ValueError(f"{option} debe ser un índice entre 0 y 50.")
        return int(value)

    bitrate = values.get("-vb", "4800k")
    if not _BITRATE_RE.fullmatch(bitrate):
        raise ValueError("Bitrate inválido; usa, por ejemplo, 4800k.")
    preset = values.get("-p", "superfast")
    if preset not in ALLOWED_PRESETS:
        raise ValueError("Preset no permitido.")
    return EncodeOptions(
        audio_index=ordinal("-a"),
        subtitle_index=ordinal("-s") if burn_subtitles else 0,
        bitrate=bitrate,
        preset=preset,
    )


def safe_filename(filename: str, fallback: str = "archivo") -> str:
    """Devuelve solo un nombre de archivo, sin rutas ni caracteres de control."""
    name = Path(filename or "").name.replace("\x00", "")
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")
    if not name or name in {".", ".."}:
        name = fallback
    return name[:180]


def ffmpeg_pass_one(
    input_path: Path,
    passlog: Path,
    options: EncodeOptions,
    filters: list[str],
) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error",
        "-i", str(input_path), "-map", "0:v:0",
    ]
    if filters:
        command += ["-vf", ",".join(filters)]
    command += [
        "-c:v", "libx264", "-b:v", options.bitrate, "-preset", options.preset,
        "-tune", "animation", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-pass", "1", "-passlogfile", str(passlog), "-an", "-sn",
        "-f", "null", os.devnull,
    ]
    return command


def ffmpeg_pass_two(
    input_path: Path,
    output_path: Path,
    passlog: Path,
    options: EncodeOptions,
    filters: list[str],
) -> list[str]:
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error",
        "-i", str(input_path), "-map", "0:v:0", "-map", f"0:a:{options.audio_index}",
    ]
    if filters:
        command += ["-vf", ",".join(filters)]
    command += [
        "-c:v", "libx264", "-b:v", options.bitrate, "-preset", options.preset,
        "-tune", "animation", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-pass", "2", "-passlogfile", str(passlog), "-c:a", "aac",
        "-b:a", "128k", "-ac", "2", "-ar", "44100", "-sn",
        "-movflags", "+faststart", str(output_path),
    ]
    return command
