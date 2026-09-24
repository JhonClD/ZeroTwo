"""Utilidades de subtítulos para ZeroTwo.

La traducción es opcional: se activa definiendo LIBRETRANSLATE_URL y, si aplica,
LIBRETRANSLATE_API_KEY. Sin esa configuración el bot sigue funcionando sin red.
"""

import html
import logging
import os
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

COLORS = {
    "white": ("Blanco", "&H00FFFFFF"),
    "yellow": ("Amarillo", "&H0000FFFF"),
    "cyan": ("Cian", "&H00FFFF00"),
    "green": ("Verde", "&H0000FF00"),
}
ALIGNMENTS = {
    "bottom": ("Abajo", 2),
    "top": ("Arriba", 8),
    "center": ("Centro", 5),
    "bottom_left": ("Abajo izquierda", 1),
    "bottom_right": ("Abajo derecha", 3),
}
LANGUAGES = {"es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés"}
FONTS = {
    "default": ("Predeterminada / conservar", ""),
    "jkanime": ("Roboto", "Roboto"),
    "dejavu": ("Noto Sans", "Noto Sans"),
    "liberation": ("Liberation Sans", "Liberation Sans"),
    "serif": ("DejaVu Serif", "DejaVu Serif"),
    "mono": ("DejaVu Sans Mono", "DejaVu Sans Mono"),
}


def ass_style(color="white", alignment="bottom", font_size=20, outline=2, font="dejavu", margin_v=12):
    """Devuelve el fragmento force_style de FFmpeg sin permitir inyección."""
    color_code = COLORS.get(color, COLORS["white"])[1]
    align_code = ALIGNMENTS.get(alignment, ALIGNMENTS["bottom"])[1]
    font_size = max(12, min(64, int(font_size)))
    outline = max(0, min(8, int(outline)))
    margin_v = max(0, min(120, int(margin_v)))
    font_name = FONTS.get(font, FONTS["default"])[1]
    font_clause = f"Fontname={font_name}," if font_name else ""
    return (
        "force_style='"
        f"{font_clause}FontSize={font_size},Bold=1,"
        f"PrimaryColour={color_code},OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline={outline},Shadow=1,Alignment={align_code},"
        f"MarginV={margin_v},WrapStyle=2'"
    )


def _cue_blocks(text):
    return re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))


def _cue_text(block):
    lines = block.split("\n")
    if not lines:
        return "", []
    start = 0
    if lines[0].strip().upper() == "WEBVTT" or lines[0].strip().startswith("NOTE"):
        return "", lines
    if re.match(r"^\d+$", lines[0].strip()):
        start = 2
    elif "-->" in lines[0]:
        start = 1
    else:
        return "", lines
    if start >= len(lines) or "-->" not in lines[start - 1]:
        return "", lines
    return "\n".join(lines[start:]), lines


def translate_subtitle_file(input_path, output_path, target_lang):
    """Traduce cues SRT/VTT usando LibreTranslate y devuelve la ruta de salida."""
    endpoint = os.getenv("LIBRETRANSLATE_URL", "").strip()
    if not endpoint:
        raise RuntimeError("La traducción no está configurada: define LIBRETRANSLATE_URL.")
    source = Path(input_path)
    if source.suffix.lower() not in {".srt", ".vtt"}:
        raise RuntimeError("La traducción automática admite .srt y .vtt; convierte ASS primero.")
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    blocks = _cue_blocks(text)
    session = requests.Session()
    translated = []
    api_key = os.getenv("LIBRETRANSLATE_API_KEY", "").strip()
    for block in blocks:
        cue, lines = _cue_text(block)
        if not cue:
            translated.append(block)
            continue
        payload = {"q": cue, "source": "auto", "target": target_lang, "format": "text"}
        if api_key:
            payload["api_key"] = api_key
        response = session.post(endpoint.rstrip("/") + "/translate", json=payload, timeout=45)
        response.raise_for_status()
        result = response.json().get("translatedText")
        if not result:
            raise RuntimeError("El servicio de traducción no devolvió texto.")
        prefix = len(lines) - len(cue.split("\n"))
        translated.append("\n".join(lines[:prefix] + [html.unescape(result)]))
    Path(output_path).write_text("\n\n".join(translated), encoding="utf-8")
    return Path(output_path)


def language_label(code):
    return LANGUAGES.get(code, code.upper())


def color_label(code):
    return COLORS.get(code, COLORS["white"])[0]


def alignment_label(code):
    return ALIGNMENTS.get(code, ALIGNMENTS["bottom"])[0]


def translation_configured():
    return bool(os.getenv("LIBRETRANSLATE_URL", "").strip())


def safe_filename(name):
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name)[:160] or "subtitles.srt"


def escape_filter_path(path):
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def format_size(path):
    size = Path(path).stat().st_size
    return f"{size / (1024 * 1024):.1f} MB"


def clean_caption(value):
    return html.escape(str(value))


def log_translation_error(error):
    logger.warning("Traducción de subtítulos no disponible: %s", error)
    return str(error)


__all__ = ["COLORS", "ALIGNMENTS", "LANGUAGES", "FONTS", "ass_style", "translate_subtitle_file", "language_label", "color_label", "alignment_label", "translation_configured", "safe_filename", "escape_filter_path", "format_size", "clean_caption", "log_translation_error"]
