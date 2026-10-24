"""Validación y utilidades de integración con el CLI externo aniDL."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


class AniDLError(ValueError):
    """La solicitud para aniDL no cumple el formato admitido."""


@dataclass(frozen=True)
class AniDLOptions:
    dub_language: str = "jpn"
    download_subtitles: str = "all"
    hard_subtitle_language: str | None = None
    quality: int = 4
    container: str = "mp4"


_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
_LANGUAGES = frozenset({
    "en", "en-IN", "es-419", "es-ES", "pt-BR", "pt-PT", "fr", "de", "ar",
    "it", "ru", "tr", "hi", "zh", "zh-CN", "zh-TW", "ko", "ca-ES", "pl-PL",
    "th-TH", "ta-IN", "ms-MY", "vi-VN", "id-ID", "te-IN", "ja", "eng", "spa",
    "spa-419", "spa-ES", "por", "fra", "deu", "ara-ME", "ara", "ita", "rus",
    "tur", "hin", "cmn", "zho", "chi", "kor", "cat", "pol", "tha", "tam",
    "may", "vie", "ind", "tel", "jpn",
})
_EPISODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")


def extract_episode_id(url: str) -> str:
    """Extrae un ID de un enlace seguro de episodio de Crunchyroll."""
    try:
        parsed = urlsplit(url.strip())
    except ValueError as error:
        raise AniDLError("El enlace no es válido.") from error
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not (
        host == "crunchyroll.com" or host.endswith(".crunchyroll.com")
    ):
        raise AniDLError("Se requiere un enlace HTTPS de crunchyroll.com.")
    try:
        has_nonstandard_authority = bool(parsed.username or parsed.password or parsed.port)
    except ValueError as error:
        raise AniDLError("El enlace contiene una autoridad no admitida.") from error
    if has_nonstandard_authority:
        raise AniDLError("El enlace contiene una autoridad no admitida.")
    segments = [part for part in parsed.path.split("/") if part]
    try:
        watch_index = segments.index("watch")
        episode_id = segments[watch_index + 1]
    except (ValueError, IndexError) as error:
        raise AniDLError("El enlace debe apuntar a /watch/ID_DEL_EPISODIO.") from error
    if not _EPISODE_ID_RE.fullmatch(episode_id):
        raise AniDLError("El identificador del episodio no tiene un formato admitido.")
    return episode_id


def parse_options(text: str) -> AniDLOptions:
    """Interpreta solo las opciones explícitamente permitidas para aniDL."""
    try:
        tokens = shlex.split(text)
    except ValueError as error:
        raise AniDLError("No pude interpretar las opciones del comando.") from error

    values: dict[str, str] = {}
    container: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--mp4", "--mkv"}:
            if container is not None:
                raise AniDLError("Elige solo un formato: --mp4 o --mkv.")
            container = token[2:]
            i += 1
            continue

        option, equals, inline_value = token.partition("=")
        if option not in {"--dubLang", "--dlsubs", "--hslang", "-q"}:
            raise AniDLError(f"Opción no admitida: {option[:32]}.")
        if option in values:
            raise AniDLError(f"La opción {option} no se puede repetir.")
        if equals:
            value = inline_value
        else:
            i += 1
            if i >= len(tokens):
                raise AniDLError(f"Falta el valor de {option}.")
            value = tokens[i]
        if not value or value.startswith("-"):
            raise AniDLError(f"Valor no válido para {option}.")
        values[option] = value
        i += 1

    dub_language = values.get("--dubLang", "jpn")
    download_subtitles = values.get("--dlsubs", "all")
    hard_subtitle_language = values.get("--hslang")
    if dub_language not in _LANGUAGES:
        raise AniDLError("El código de idioma de audio no está en la lista admitida por AniDL.")
    if download_subtitles not in _LANGUAGES | {"all", "none"}:
        raise AniDLError("El código de subtítulos suaves no está admitido por AniDL.")
    if hard_subtitle_language is not None and hard_subtitle_language not in _LANGUAGES:
        raise AniDLError("El código de subtítulos incrustados no está admitido por AniDL.")
    try:
        quality = int(values.get("-q", "4"))
    except ValueError as error:
        raise AniDLError("La calidad debe ser un número del 1 al 5.") from error
    if quality not in range(1, 6):
        raise AniDLError("La calidad debe ser un número del 1 al 5.")

    return AniDLOptions(
        dub_language=dub_language,
        download_subtitles=download_subtitles,
        hard_subtitle_language=hard_subtitle_language,
        quality=quality,
        container=container or "mp4",
    )


def build_command(executable: str, episode_id: str, options: AniDLOptions) -> list[str]:
    """Construye argv sin shell ni interpolación de texto del usuario."""
    if not _EPISODE_ID_RE.fullmatch(episode_id):
        raise AniDLError("El identificador del episodio no es válido.")
    # AniDL usa -e para object IDs de Crunchyroll y --extid para IDs externos/legacy.
    id_flag = "--extid" if len(episode_id) > 9 else "-e"
    command = [
        executable,
        "--service", "crunchy",
        id_flag, episode_id,
        "--dubLang", options.dub_language,
        "--dlsubs", options.download_subtitles,
    ]
    if options.hard_subtitle_language:
        command.extend(["--hslang", options.hard_subtitle_language])
    command.extend([
        "-q", str(options.quality),
        f"--{options.container}",
        "--force", "y",
    ])
    return command


def snapshot_videos(output_dir: str | Path) -> dict[Path, tuple[int, int]]:
    """Registra tamaños y fechas previos sin seguir enlaces simbólicos."""
    root = Path(output_dir)
    snapshot: dict[Path, tuple[int, int]] = {}
    if not root.is_dir():
        return snapshot
    for path in root.iterdir():
        try:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in _VIDEO_EXTENSIONS:
                continue
            stat = path.stat()
            snapshot[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
    return snapshot


def changed_videos(
    output_dir: str | Path,
    before: dict[Path, tuple[int, int]],
) -> list[Path]:
    """Lista medios nuevos o modificados por esta ejecución, sin borrarlos."""
    root = Path(output_dir)
    changed: list[tuple[int, Path]] = []
    if not root.is_dir():
        return []
    for path in root.iterdir():
        try:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in _VIDEO_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved.parent != root.resolve():
                continue
            stat = path.stat()
            state = (stat.st_mtime_ns, stat.st_size)
            if before.get(resolved) != state and stat.st_size > 0:
                changed.append((stat.st_mtime_ns, resolved))
        except OSError:
            continue
    return [path for _, path in sorted(changed)]
