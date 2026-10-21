"""Helpers de presentación para progreso de transferencias en Telegram."""

from __future__ import annotations

from collections import deque
from html import escape
import mimetypes
from pathlib import Path
import re
import time
from typing import Callable


_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
_SIZE_FACTORS = {
    "B": 1,
    "K": 1024, "KB": 1024, "KIB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
    "T": 1024 ** 4, "TB": 1024 ** 4, "TIB": 1024 ** 4,
    "P": 1024 ** 5, "PB": 1024 ** 5, "PIB": 1024 ** 5,
}


def parse_bytes(value: str | int | float | None) -> int | None:
    """Convierte expresiones comunes de aria2/megatools a bytes."""
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not value:
        return None
    match = re.search(r"([\d.]+)\s*([KMGTPE]?i?B?|[KMGTPE])", str(value), re.IGNORECASE)
    if not match:
        return None
    unit = match.group(2).upper().replace("IB", "IB")
    if unit.endswith("IB") and unit != "B":
        unit = unit[0] + "IB"
    elif unit.endswith("B"):
        unit = unit
    else:
        unit += "B"
    factor = _SIZE_FACTORS.get(unit)
    try:
        return int(float(match.group(1)) * factor) if factor else None
    except (TypeError, ValueError, OverflowError):
        return None


def format_bytes(value: int | float) -> str:
    """Formatea bytes con unidades binarias legibles."""
    try:
        number = max(0.0, float(value))
    except (TypeError, ValueError):
        number = 0.0
    for unit in _UNITS:
        if number < 1024 or unit == _UNITS[-1]:
            return f"{int(number)} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} PB"


def format_duration(seconds: float | None) -> str:
    """Devuelve una duración corta para ETA; usa — si no se puede estimar."""
    if seconds is None:
        return "—"
    try:
        remaining = max(0, int(seconds))
    except (TypeError, ValueError, OverflowError):
        return "—"
    hours, remainder = divmod(remaining, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def progress_bar(percent: float, width: int = 12) -> str:
    """Genera una barra de progreso que tolera porcentajes fuera de rango."""
    width = max(1, int(width))
    try:
        bounded = min(100.0, max(0.0, float(percent)))
    except (TypeError, ValueError):
        bounded = 0.0
    filled = min(width, int(width * bounded / 100))
    return "▓" * filled + "░" * (width - filled)


class TransferProgress:
    """Calcula velocidad reciente y ETA a partir de callbacks de bytes."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque(maxlen=20)

    def snapshot(self, current: int | float, total: int | float = 0) -> dict[str, int | float | None]:
        try:
            current_bytes = max(0, int(current or 0))
        except (TypeError, ValueError, OverflowError):
            current_bytes = 0
        try:
            total_bytes = max(0, int(total or 0))
        except (TypeError, ValueError, OverflowError):
            total_bytes = 0

        now = self._clock()
        self._samples.append((now, current_bytes))
        cutoff = now - 10.0
        while len(self._samples) > 2 and self._samples[1][0] < cutoff:
            self._samples.popleft()

        speed: float | None = None
        if len(self._samples) >= 2:
            elapsed = self._samples[-1][0] - self._samples[0][0]
            delta = self._samples[-1][1] - self._samples[0][1]
            if elapsed > 0 and delta >= 0:
                speed = delta / elapsed

        percent = min(100.0, current_bytes * 100.0 / total_bytes) if total_bytes else None
        eta = (max(0, total_bytes - current_bytes) / speed) if total_bytes and speed and speed > 0 else None
        return {
            "current": current_bytes,
            "total": total_bytes,
            "percent": percent,
            "speed": speed,
            "eta": eta,
        }


def render_transfer_status(
    stage: str,
    source: str,
    filename: str,
    current: int | float,
    total: int | float,
    tracker: TransferProgress,
    context: str | None = None,
    speed_override: int | float | None = None,
) -> str:
    """Construye una tarjeta HTML uniforme para una descarga o subida."""
    snapshot = tracker.snapshot(current, total)
    percent = snapshot["percent"]
    current_text = format_bytes(snapshot["current"] or 0)
    total_text = format_bytes(snapshot["total"] or 0)
    safe_name = escape(Path(str(filename or "archivo")).name.replace("\x00", ""))
    icon = "📥" if "descarg" in stage.casefold() or "recib" in stage.casefold() else "📤"
    lines = [f"{icon} <b>{escape(stage)} · {escape(source)}</b>"]
    if context:
        lines.append(f"ℹ️ {escape(context)}")
    lines.append(f"📄 <code>{safe_name or 'archivo'}</code>")
    if percent is None:
        lines.append(f"📦 {current_text} transferidos · tamaño total desconocido")
    else:
        pct_text = f"{percent:.0f}%"
        lines.append(f"📦 {current_text} / {total_text} · {pct_text}")
        lines.append(f"{progress_bar(percent)} {pct_text}")

    speed = speed_override if speed_override is not None else snapshot["speed"]
    eta = (max(0, (snapshot["total"] - snapshot["current"]) / speed)
           if speed and speed > 0 and snapshot["total"] else snapshot["eta"])
    if speed is not None:
        detail = f"⚡ {format_bytes(speed)}/s"
        if eta is not None:
            detail += f" · ⏳ {format_duration(eta)}"
        lines.append(detail)
    return "\n".join(lines)


def format_file_info(file_path: str | Path, source: str | None = None) -> str:
    """Devuelve nombre, tipo y tamaño del archivo descargado."""
    path = Path(file_path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    mime_type = mimetypes.guess_type(path.name)[0] or "tipo desconocido"
    extension = path.suffix.lstrip(".").upper()
    file_type = f"{extension} · {mime_type}" if extension else mime_type
    lines = [f"📄 <code>{escape(path.name.replace(chr(0), ''))}</code>"]
    lines.append(f"🗂 Tipo: {escape(file_type)}")
    lines.append(f"📦 Tamaño: {format_bytes(size)}")
    if source:
        lines.append(f"🌐 Origen: {escape(source)}")
    return "\n".join(lines)
