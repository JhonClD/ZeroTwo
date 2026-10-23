"""Integración opcional con el CLI oficial AniDL.

Solo ejecuta el binario ya instalado por el propietario. No contiene credenciales,
no acepta opciones de shell y limita cada solicitud a un episodio.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import signal
import uuid
from pathlib import Path

from pyrogram import enums, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_RE = re.compile(
    r"(?i)\b(access[_ -]?token|refresh[_ -]?token|authorization|password|passwd)"
    r"(\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;]+"
)
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,99}\Z")
_EPISODE_RE = re.compile(r"(?:[1-9]\d{0,3}|S[1-9]\d{0,3})\Z", re.IGNORECASE)
_VIDEO_EXTENSIONS = {".mkv", ".mp4"}
_MAX_CAPTURE_BYTES = 256 * 1024
_DOWNLOAD_LOCK = asyncio.Lock()
_ACTIVE_PROCESSES: dict[int, asyncio.subprocess.Process] = {}


class AniDLError(RuntimeError):
    """Error seguro y presentable al usuario para problemas del CLI AniDL."""


def _allowed_user_ids() -> set[int]:
    """Carga la allowlist explícita; sin configuración la función queda cerrada."""
    raw = os.getenv("ZERO_TWO_ANIDL_ALLOWED_IDS", "")
    allowed: set[int] = set()
    for value in raw.split(","):
        value = value.strip()
        if value.isdigit():
            user_id = int(value)
            if user_id > 0:
                allowed.add(user_id)
    return allowed


def _valid_id(value: str) -> bool:
    return bool(_ID_RE.fullmatch(value))


def _valid_episode(value: str) -> bool:
    return bool(_EPISODE_RE.fullmatch(value))


def _int_setting(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _resolve_executable() -> Path:
    configured = os.getenv("ZERO_TWO_ANIDL_BIN", "").strip()
    candidates = [configured] if configured else ["aniDL", "AniDL"]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.sep in candidate or (os.path.altsep and os.path.altsep in candidate):
            path = Path(candidate).expanduser()
            if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK)):
                return path.resolve()
        else:
            found = shutil.which(candidate)
            if found:
                return Path(found).resolve()
    raise AniDLError(
        "No encuentro AniDL. Instala una versión oficial compatible y configura "
        "ZERO_TWO_ANIDL_BIN si no está en PATH."
    )


def _context() -> tuple[Path, Path, Path]:
    """Devuelve ejecutable, directorio de trabajo AniDL y directorio de salida."""
    executable = _resolve_executable()
    raw_home = os.getenv("ZERO_TWO_ANIDL_HOME", "").strip()
    home = Path(raw_home).expanduser().resolve() if raw_home else executable.parent
    if not home.is_dir():
        raise AniDLError("ZERO_TWO_ANIDL_HOME debe apuntar a una carpeta existente de AniDL.")

    raw_output = os.getenv("ZERO_TWO_ANIDL_OUTPUT_DIR", "").strip()
    output_root = Path(raw_output).expanduser().resolve() if raw_output else (home / "videos").resolve()
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AniDLError("No se puede preparar la carpeta de salida de AniDL.") from error
    return executable, home, output_root


def _child_environment(home: Path) -> dict[str, str]:
    """Pasa al proceso solo variables necesarias; excluye el token del bot."""
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "XDG_CONFIG_HOME",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
    )
    child = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    child.setdefault("HOME", str(Path.home()))
    child["contentDirectory"] = str(home)
    return child


def _download_args(season_id: str, episode: str, job_name: str) -> list[str]:
    """Construye argumentos validados; el job name se genera internamente."""
    filename = (
        f"{job_name}/[${{service}}] ${{showTitle}} - "
        f"S${{season}}E${{episode}} [${{height}}p]"
    )
    return [
        "--service",
        "crunchy",
        "-s",
        season_id,
        "-e",
        episode,
        "--fileName",
        filename,
        "--skipUpdate",
    ]


def _safe_output_text(raw: bytes | str, limit: int = 2800) -> str:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text).replace("\r", "\n").strip()
    text = _SECRET_RE.sub(r"\1\2[oculto]", text)
    return text[-limit:]


async def _read_tail(stream) -> bytes:
    tail = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        tail.extend(chunk)
        if len(tail) > _MAX_CAPTURE_BYTES:
            del tail[: len(tail) - _MAX_CAPTURE_BYTES]
    return bytes(tail)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=8)
        return
    except asyncio.TimeoutError:
        pass
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=8)
    except asyncio.TimeoutError:
        logger.error("AniDL no terminó tras SIGKILL/kill.")


async def _run_cli(
    executable: Path,
    home: Path,
    args: list[str],
    timeout: int,
    active_user_id: int | None = None,
) -> tuple[int, str]:
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(
            str(executable),
            *args,
            cwd=str(home),
            env=_child_environment(home),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )
    except FileNotFoundError as error:
        raise AniDLError("No se pudo iniciar el ejecutable AniDL configurado.") from error
    except OSError as error:
        raise AniDLError("El sistema no pudo iniciar AniDL; revisa permisos y arquitectura.") from error

    if active_user_id is not None:
        _ACTIVE_PROCESSES[active_user_id] = process
    reader = asyncio.create_task(_read_tail(process.stdout))
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=timeout)
    except asyncio.TimeoutError as error:
        await _stop_process(process)
        await reader
        raise AniDLError(f"AniDL superó el límite de {timeout // 60} minutos.") from error
    except asyncio.CancelledError:
        await _stop_process(process)
        await reader
        raise
    finally:
        if active_user_id is not None and _ACTIVE_PROCESSES.get(active_user_id) is process:
            _ACTIVE_PROCESSES.pop(active_user_id, None)

    output = await reader
    return int(process.returncode or 0), _safe_output_text(output)


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(root.resolve()))) == str(root.resolve())
    except (OSError, ValueError):
        return False


def _video_outputs(job_dir: Path) -> list[Path]:
    if not job_dir.is_dir():
        return []
    root = job_dir.resolve()
    found = []
    for path in job_dir.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in _VIDEO_EXTENSIONS:
                resolved = path.resolve(strict=True)
                if _within(resolved, root):
                    found.append(resolved)
        except OSError:
            continue
    return sorted(found)


def _cleanup_job(job_dir: Path, output_root: Path) -> None:
    target = job_dir.resolve()
    root = output_root.resolve()
    if target == root or not _within(target, root):
        logger.error("Se rechazó limpiar una carpeta AniDL fuera del directorio de salida.")
        return
    shutil.rmtree(target, ignore_errors=True)


async def _show_cli_result(status: Message, heading: str, returncode: int, output: str) -> None:
    safe_output = output[-700:] if output else "AniDL no devolvió texto."
    result = "✅" if returncode == 0 else "⚠️"
    text = f"{result} <b>{html.escape(heading)}</b>\n<pre>{html.escape(safe_output)}</pre>"
    try:
        await status.edit_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("No se pudo actualizar el mensaje del comando AniDL.")


def register(app) -> None:
    @app.on_message(filters.command(["anidlsearch", "anidlseries", "anidl", "anidlcancel"]))
    async def anidl_command(client, message: Message):
        sender = message.from_user
        if message.chat.type != enums.ChatType.PRIVATE:
            await message.reply_text("Por seguridad, los comandos AniDL solo están disponibles en chat privado.")
            return
        allowed = _allowed_user_ids()
        if not sender or sender.id not in allowed:
            await message.reply_text(
                "⛔ AniDL está desactivado para este usuario. El propietario debe configurar "
                "ZERO_TWO_ANIDL_ALLOWED_IDS."
            )
            return

        raw_text = (message.text or "").strip()
        pieces = raw_text.split(maxsplit=1)
        command = pieces[0].split("@", 1)[0].lstrip("/").lower() if pieces else ""
        payload = pieces[1].strip() if len(pieces) > 1 else ""

        if command == "anidlcancel":
            process = _ACTIVE_PROCESSES.get(sender.id)
            if not process or process.returncode is not None:
                await message.reply_text("No tienes una descarga AniDL activa.")
                return
            await _stop_process(process)
            await message.reply_text("⏹️ Se detuvo el proceso AniDL activo.")
            return

        if command == "anidlsearch":
            query = payload.strip()
            if not query or len(query) > 120 or query.startswith("-") or any(ch in query for ch in "\r\n\x00"):
                await message.reply_text("Uso: <code>/anidlsearch nombre de la serie</code>", parse_mode=enums.ParseMode.HTML)
                return
            cli_args = ["--service", "crunchy", "--search", query, "--search-type", "series", "--page", "1", "--skipUpdate"]
            heading = "Resultados AniDL. Copia el ID de la serie para consultar sus temporadas."
            timeout = 90
        elif command == "anidlseries":
            series_id = payload.strip()
            if not _valid_id(series_id):
                await message.reply_text("Uso: <code>/anidlseries ID_DE_SERIE</code>", parse_mode=enums.ParseMode.HTML)
                return
            cli_args = ["--service", "crunchy", "--series", series_id, "--skipUpdate"]
            heading = "Temporadas AniDL. Copia el ID de la temporada para descargar un episodio."
            timeout = 90
        elif command == "anidl":
            values = payload.split()
            if len(values) != 2 or not _valid_id(values[0]) or not _valid_episode(values[1]):
                await message.reply_text(
                    "Uso: <code>/anidl ID_DE_TEMPORADA EPISODIO</code>\n"
                    "Ejemplo: <code>/anidl ID_DE_TEMPORADA 3</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
                return
            season_id, episode = values
            try:
                executable, home, output_root = _context()
            except AniDLError as error:
                await message.reply_text(html.escape(str(error)))
                return

            if _DOWNLOAD_LOCK.locked():
                await message.reply_text("Ya hay una descarga AniDL en curso. Intenta más tarde o usa /anidlcancel.")
                return

            await _DOWNLOAD_LOCK.acquire()
            job_name = f"zerotwo_{uuid.uuid4().hex[:16]}"
            job_dir = output_root / job_name
            try:
                try:
                    job_dir.mkdir(parents=True, exist_ok=False)
                except OSError:
                    await message.reply_text("No se pudo crear una carpeta temporal segura para AniDL.")
                    return

                cli_args = _download_args(season_id, episode, job_name)
                timeout = _int_setting("ZERO_TWO_ANIDL_TIMEOUT", 3600, 60, 7200)
                max_mb = _int_setting("ZERO_TWO_ANIDL_MAX_MB", 1800, 50, 2048)
                status = await message.reply_text("⏬ AniDL inició la descarga de un episodio. Usa /anidlcancel para detenerla.")
                try:
                    returncode, output = await _run_cli(executable, home, cli_args, timeout, sender.id)
                    if returncode != 0:
                        logger.warning("AniDL terminó con código %d.", returncode)
                        await status.edit_text("❌ AniDL no completó la descarga. Revisa la instalación y la autenticación local de AniDL.")
                        return
                    videos = _video_outputs(job_dir)
                    if len(videos) != 1:
                        await status.edit_text(
                            "❌ AniDL no produjo exactamente un archivo de video para este episodio. "
                            "Revisa la configuración local de salida."
                        )
                        return
                    video = videos[0]
                    size_mb = video.stat().st_size / (1024 * 1024)
                    if size_mb > max_mb:
                        await status.edit_text(f"❌ El archivo supera el límite configurado de {max_mb} MB.")
                        return
                    await status.edit_text(f"✅ AniDL terminó ({size_mb:.1f} MB). Enviando el archivo…")
                    caption = "AniDL · episodio descargado"
                    if video.suffix.lower() == ".mp4":
                        await client.send_video(message.chat.id, str(video), caption=caption, supports_streaming=True)
                    else:
                        await client.send_document(message.chat.id, str(video), caption=caption)
                    await status.delete()
                except AniDLError as error:
                    await status.edit_text(f"❌ {html.escape(str(error))}")
                except Exception:
                    logger.exception("Error durante la descarga AniDL para usuario autorizado.")
                    try:
                        await status.edit_text("❌ Falló la descarga o el envío del archivo. Revisa bot.log.")
                    except Exception:
                        pass
            finally:
                _ACTIVE_PROCESSES.pop(sender.id, None)
                _cleanup_job(job_dir, output_root)
                _DOWNLOAD_LOCK.release()
            return
        else:
            return

        try:
            executable, home, _ = _context()
        except AniDLError as error:
            await message.reply_text(html.escape(str(error)))
            return
        status = await message.reply_text("🔎 AniDL está consultando el catálogo…")
        try:
            returncode, output = await _run_cli(executable, home, cli_args, timeout)
            await _show_cli_result(status, heading, returncode, output)
        except AniDLError as error:
            await status.edit_text(f"❌ {html.escape(str(error))}")
        except Exception:
            logger.exception("Error ejecutando una consulta AniDL.")
            await status.edit_text("❌ No se pudo consultar AniDL. Revisa la instalación local.")

    logger.info("Handler AniDL registrado; acceso privado controlado por ZERO_TWO_ANIDL_ALLOWED_IDS")
