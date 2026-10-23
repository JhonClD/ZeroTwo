"""Comando /unrar para descomprimir archivos RAR recibidos por Telegram."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from pyrogram import StopPropagation, enums, filters
from pyrogram.types import Message

from utils.rar_archives import inspect_archive
from utils.transfer_status import TransferProgress

logger = logging.getLogger(__name__)
VIDEO_EXTENSIONS = frozenset({
    ".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".mts", ".ogv", ".ts", ".webm", ".wmv",
})


def _is_video_file(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in VIDEO_EXTENSIONS


def _probe_video(path: str | Path) -> tuple[float, int, int] | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        metadata = json.loads(result.stdout)
        stream = next(iter(metadata.get("streams", [])), {})
        duration_value = metadata.get("format", {}).get("duration") or stream.get("duration")
        duration = float(duration_value) if duration_value is not None else 0.0
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if duration <= 0 or width <= 0 or height <= 0:
            return None
        return duration, width, height
    except (OSError, ValueError, TypeError, StopIteration, subprocess.SubprocessError):
        return None


def _create_video_thumbnail(path: str | Path, thumb_path: str | Path, duration: float) -> str | None:
    thumb_path = Path(thumb_path)
    seek = max(0.0, min(duration * 0.1, 30.0))
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{seek:.3f}",
                "-i", str(path), "-frames:v", "1", "-vf",
                "scale=320:320:force_original_aspect_ratio=decrease",
                "-q:v", "9", "-y", str(thumb_path),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=45,
        )
        if result.returncode == 0 and thumb_path.is_file() and thumb_path.stat().st_size <= 200_000:
            return str(thumb_path)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        thumb_path.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def _mib(value: int | float) -> str:
    return f"{max(0, value) / (1024 * 1024):.1f} MiB"


def _elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _status(
    filename: str,
    current: int,
    total: int,
    files_current: int,
    files_total: int,
    started_at: float,
    meter: TransferProgress,
    task_id: str,
    stage: str = "Descomprimiendo...",
) -> str:
    percent = 100.0 if stage == "✓ Descomprimido" else (min(100.0, current * 100.0 / total) if total else 0.0)
    filled = min(13, int(13 * percent / 100))
    bar = "■" * filled + "□" * (13 - filled)
    elapsed = max(0.0, time.monotonic() - started_at)
    snapshot = meter.snapshot(current, total)
    speed = snapshot["speed"]
    if not speed and elapsed >= 1:
        speed = current / elapsed
    eta = (max(0, total - current) / speed) if speed and speed > 0 and total else None
    lines = [
        f"<b>{html.escape(Path(filename).name)}</b>\n",
        f"┃ [{bar}] {percent:05.2f}%\n",
        f"┠ Size: {_mib(current)} / {_mib(total) if total else 'desconocido'}\n",
        f"┠ Status: {html.escape(stage)}\n",
        f"┠ Files: {files_current} / {files_total if files_total else '?'}\n",
    ]
    if stage == "✓ Descomprimido":
        lines.append(f"┠ Time: {_elapsed(elapsed)}\n")
        lines.append("┗ Mode: #Extract | #RAR")
    else:
        if stage == "Descomprimiendo...":
            lines.append(f"┠ Speed: {_mib(speed or 0)}/s | ETA: {_duration(eta)}\n")
            lines.append(f"┠ Elapsed: {_elapsed(elapsed)}\n")
        lines.append("┠ Mode: #Extract | #RAR\n")
        lines.append(f"┗ Cancelar: /cancel {task_id}")
    return "".join(lines)


def _available_extractor() -> tuple[str, str] | None:
    for name in ("unrar", "unar", "7zz", "7z"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


def _extract_command(tool: str, archive: Path, destination: Path, password: str | None) -> list[str]:
    if tool == "unrar":
        password_arg = f"-p{password}" if password is not None else "-p-"
        return ["unrar", "x", "-o+", "-idq", password_arg, str(archive), f"{destination}{os.sep}"]
    if tool == "unar":
        args = ["unar", "-f", "-o", str(destination)]
        if password is not None:
            args.extend(["-p", password])
        args.append(str(archive))
        return args
    args = [tool, "x", "-y", "-bsp0", f"-o{destination}"]
    if password is not None:
        args.append(f"-p{password}")
    args.append(str(archive))
    return args


def _error_reason(return_code: int | None, tool_output: str) -> str:
    text = tool_output.casefold()
    if any(term in text for term in ("wrong password", "password is incorrect", "incorrect password", "bad password", "contraseña incorrecta")):
        return "contraseña incorrecta"
    if any(term in text for term in ("no space left", "not enough space", "disk full", "sin espacio")):
        return "sin espacio disponible"
    if any(term in text for term in (
        "corrupt", "crc failed", "checksum error", "unexpected end", "archive is damaged",
        "is not archive", "not a rar", "not an archive", "can't open as archive",
    )):
        return "archivo corrupto o dañado"
    if return_code == 11:
        return "contraseña incorrecta o archivo protegido"
    return "error del extractor o archivo no compatible"


def register(app, download_dir: Path) -> None:
    """Registra /unrar y el comando /cancel para sus tareas activas."""
    root = Path(download_dir)
    jobs: dict[str, dict] = {}
    password_waiters: dict[tuple[int, int], asyncio.Future] = {}
    user_jobs: dict[tuple[int, int], str] = {}

    @app.on_message(filters.text, group=-4)
    async def receive_password(client, message: Message):
        if not message.from_user or message.from_user.is_bot or not message.text or message.text.startswith("/"):
            return
        key = (message.chat.id, message.from_user.id)
        future = password_waiters.get(key)
        if future is None or future.done():
            return
        job_id = user_jobs.get(key)
        state = jobs.get(job_id) if job_id else None
        status = state.get("status") if state else None
        if status is not None:
            try:
                await status.edit_text(
                    f"<b>{html.escape(state.get('display_name', 'archivo.rar'))}</b>\n"
                    "┃ 🔓 Contraseña recibida\n"
                    "┠ Status: Verificando contraseña...\n"
                    f"┠ Mode: #Extract | #RAR\n"
                    f"┗ Cancelar: /cancel {job_id}",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        future.set_result(message.text)
        try:
            await message.delete()
        except Exception:
            pass
        raise StopPropagation

    @app.on_message(filters.command("cancel"))
    async def cancel_unrar(client, message: Message):
        args = (message.text or message.caption or "").split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text("Indica el ID de la extracción que quieres cancelar: <code>/cancel X5R9</code>", parse_mode=enums.ParseMode.HTML)
            return
        task_id = args[1].strip().upper()
        state = jobs.get(task_id)
        if not state:
            await message.reply_text("No hay una extracción RAR activa con ese ID.")
            return
        owner = (message.chat.id, message.from_user.id if message.from_user else message.chat.id)
        if owner != state["owner"]:
            await message.reply_text("Solo quien inició esta extracción puede cancelarla.")
            return
        state["cancelled"] = True
        future = state.get("password_future")
        if future is not None and not future.done():
            future.set_result(None)
        process = state.get("process")
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        elif state.get("task") and state["task"] is not asyncio.current_task():
            state["task"].cancel()
        await message.reply_text(f"Cancelando extracción <code>{html.escape(task_id)}</code>…", parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command("unrar"))
    async def unrar_command(client, message: Message):
        user_id = message.from_user.id if message.from_user else message.chat.id
        owner = (message.chat.id, user_id)
        if owner in user_jobs:
            await message.reply_text("Ya tienes una extracción RAR activa. Espera a que termine o cancélala con /cancel ID.")
            return

        text = message.text or message.caption or ""
        parts = text.split(maxsplit=1)
        requested_name = Path(parts[1].strip()).name if len(parts) > 1 else None
        source_message = message if message.document else message.reply_to_message
        media = source_message.document if source_message else None
        attached_name = Path(getattr(media, "file_name", "") or "").name if media else None

        if media and (not attached_name or not attached_name.lower().endswith(".rar")):
            await message.reply_text("El archivo adjunto debe ser un documento <code>.rar</code>.", parse_mode=enums.ParseMode.HTML)
            return
        if media and requested_name and requested_name.casefold() != attached_name.casefold():
            await message.reply_text(f"El nombre indicado no coincide con el archivo respondido: <code>{html.escape(attached_name)}</code>.", parse_mode=enums.ParseMode.HTML)
            return
        if not media and not requested_name:
            await message.reply_text(
                "Envía el archivo <code>.rar</code> como documento y responde con <code>/unrar</code>, "
                "o usa <code>/unrar nombre_archivo.rar</code> si ya está guardado en tus descargas.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        if requested_name and not requested_name.lower().endswith(".rar"):
            await message.reply_text("El archivo debe tener extensión <code>.rar</code>.", parse_mode=enums.ParseMode.HTML)
            return

        job_id = uuid.uuid4().hex[:4].upper()
        display_name = attached_name or requested_name or "archivo.rar"
        job_dir = root / f"unrar_{user_id}_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=False)
        try:
            job_dir.chmod(0o700)
        except OSError:
            pass
        archive_path = job_dir / "source.rar"
        output_dir = job_dir / "extracted"
        output_dir.mkdir()
        state = {
            "owner": owner,
            "task": asyncio.current_task(),
            "process": None,
            "password_future": None,
            "cancelled": False,
            "job_dir": job_dir,
            "status": None,
            "display_name": display_name,
        }
        jobs[job_id] = state
        user_jobs[owner] = job_id
        started_at = time.monotonic()
        meter = TransferProgress()
        status = await message.reply_text(
            _status(display_name, 0, 0, 0, 0, started_at, meter, job_id, "Descargando archivo..."),
            parse_mode=enums.ParseMode.HTML,
        )
        state["status"] = status

        async def ask_password() -> str | None:
            key = owner
            if key in password_waiters:
                raise RuntimeError("Ya existe una solicitud de contraseña activa en este chat.")
            future = asyncio.get_running_loop().create_future()
            state["password_future"] = future
            password_waiters[key] = future
            await status.edit_text(
                f"<b>{html.escape(display_name)}</b>\n"
                "┃ 🔒 Archivo protegido\n"
                "┠ Status: Requiere contraseña\n"
                "┠ Responde con la contraseña\n"
                "┠ Expira en: 60s\n"
                f"┠ Mode: #Extract | #RAR\n"
                f"┗ Cancelar: /cancel {job_id}",
                parse_mode=enums.ParseMode.HTML,
            )
            try:
                return await asyncio.wait_for(future, timeout=60)
            except asyncio.TimeoutError:
                return None
            finally:
                password_waiters.pop(key, None)
                state["password_future"] = None

        try:
            if media:
                last_download = [0.0]

                async def download_progress(current, total):
                    now = time.monotonic()
                    if total and now - last_download[0] < 1 and current < total:
                        return
                    last_download[0] = now
                    try:
                        await status.edit_text(
                            _status(display_name, current, total, 0, 0, started_at, meter, job_id, "Descargando archivo..."),
                            parse_mode=enums.ParseMode.HTML,
                        )
                    except Exception:
                        pass

                downloaded = await source_message.download(
                    file_name=str(archive_path), progress=download_progress,
                )
                if not downloaded:
                    raise RuntimeError("Telegram no entregó el archivo.")
                archive_path = Path(downloaded)
            else:
                candidates = [
                    root / f"user_{user_id}" / requested_name,
                    root / requested_name,
                ]
                local_source = next((path for path in candidates if path.is_file()), None)
                if local_source is None:
                    raise FileNotFoundError(
                        f"No encontré {requested_name} en tus descargas. Envía el .rar y responde a él con /unrar."
                    )
                await asyncio.to_thread(shutil.copy2, local_source, archive_path)

            if archive_path.stat().st_size == 0:
                raise ValueError("El archivo está vacío.")
            extractor = _available_extractor()
            if extractor is None:
                raise FileNotFoundError("No está instalado unrar, unar, 7zz ni 7z en el servidor.")
            tool_name, tool_path = extractor
            password = None
            try:
                archive_info = await asyncio.to_thread(inspect_archive, archive_path)
            except Exception as error:
                from rarfile import Error as RarError, PasswordRequired, RarWrongPassword
                if isinstance(error, PasswordRequired):
                    archive_info = None
                elif isinstance(error, RarWrongPassword):
                    raise ValueError("contraseña incorrecta") from error
                elif isinstance(error, RarError):
                    raise ValueError("archivo corrupto o dañado") from error
                else:
                    raise

            if archive_info is None or archive_info.password_required:
                password = await ask_password()
                if password is None:
                    if state["cancelled"]:
                        await status.edit_text("✗ Extracción cancelada.")
                    else:
                        await status.edit_text(
                            f"<b>{html.escape(display_name)}</b>\n"
                            "┃ ✗ Error al descomprimir\n"
                            "┠ Motivo: no se recibió la contraseña en 60 segundos\n"
                            "┗ Mode: #Extract | #RAR",
                            parse_mode=enums.ParseMode.HTML,
                        )
                    return
                if archive_info is None:
                    archive_info = await asyncio.to_thread(inspect_archive, archive_path, password)

            required_space = archive_info.total_bytes + archive_path.stat().st_size
            if shutil.disk_usage(job_dir).free < required_space:
                raise OSError("No space left on device")

            command = [tool_path, *_extract_command(tool_name, archive_path, output_dir, password)[1:]]
            log_path = job_dir / "extractor.log"
            with log_path.open("wb") as log_file:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=log_file,
                    stderr=asyncio.subprocess.STDOUT,
                )
                state["process"] = process
                last_update = 0.0
                while process.returncode is None:
                    await asyncio.sleep(1)
                    if process.returncode is not None:
                        break
                    now = time.monotonic()
                    if now - last_update < 0.8:
                        continue
                    last_update = now
                    current_paths = [path for path in output_dir.rglob("*") if path.is_file() and not path.is_symlink()]
                    current_bytes = sum(path.stat().st_size for path in current_paths)
                    try:
                        await status.edit_text(
                            _status(display_name, current_bytes, archive_info.total_bytes,
                                    len(current_paths), archive_info.files, started_at, meter, job_id),
                            parse_mode=enums.ParseMode.HTML,
                        )
                    except Exception:
                        pass
                return_code = await process.wait()
                state["process"] = None
            tool_output = log_path.read_text(errors="replace")[-8000:]
            if state["cancelled"]:
                await status.edit_text("✗ Extracción cancelada.")
                return
            if return_code != 0:
                raise RuntimeError(_error_reason(return_code, tool_output))

            output_files = []
            output_root = output_dir.resolve()
            for path in output_dir.rglob("*"):
                if path.is_symlink():
                    raise ValueError("El archivo generó un enlace simbólico; se detuvo por seguridad.")
                if path.is_file():
                    try:
                        path.resolve().relative_to(output_root)
                    except ValueError:
                        raise ValueError("El archivo intentó salir de la carpeta de extracción.")
                    output_files.append(path)
            if not output_files:
                raise RuntimeError("archivo corrupto o contraseña incorrecta; no se extrajo ningún archivo")
            total_extracted = sum(path.stat().st_size for path in output_files)
            await status.edit_text(
                _status(display_name, total_extracted, total_extracted,
                        len(output_files), len(output_files), started_at, meter, job_id, "✓ Descomprimido"),
                parse_mode=enums.ParseMode.HTML,
            )
            for index, path in enumerate(sorted(output_files)):
                try:
                    if _is_video_file(path):
                        video_metadata = await asyncio.to_thread(_probe_video, path)
                        video_args = {"video": str(path), "supports_streaming": True}
                        duration = 0.0
                        if video_metadata:
                            duration, width, height = video_metadata
                            video_args.update(
                                duration=max(1, int(round(duration))),
                                width=width,
                                height=height,
                            )
                        thumb = await asyncio.to_thread(
                            _create_video_thumbnail,
                            path,
                            job_dir / f"video_preview_{index}.jpg",
                            duration,
                        )
                        if thumb:
                            video_args["thumb"] = thumb
                        await message.reply_video(**video_args)
                    else:
                        await message.reply_document(document=str(path))
                except Exception:
                    try:
                        if _is_video_file(path):
                            await message.reply_document(
                                document=str(path),
                                caption="Telegram no aceptó el archivo como video; se envía como documento.",
                            )
                        else:
                            raise RuntimeError("No se pudo enviar el archivo como documento.")
                    except Exception:
                        await message.reply_text(
                            f"El archivo <code>{html.escape(path.name)}</code> se extrajo, pero Telegram no pudo enviarlo.",
                            parse_mode=enums.ParseMode.HTML,
                        )

        except asyncio.CancelledError:
            try:
                process = state.get("process")
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.wait()
                await status.edit_text("✗ Extracción cancelada.")
            except Exception:
                pass
        except Exception as error:
            reason = str(error) or "error desconocido"
            if "password" in reason.casefold() or "contraseña" in reason.casefold():
                reason = "contraseña incorrecta o archivo protegido"
            elif "space" in reason.casefold() or "espacio" in reason.casefold():
                reason = "sin espacio disponible"
            elif any(term in reason.casefold() for term in ("corrupt", "crc", "damaged", "raropenerror", "rarcrcerror")):
                reason = "archivo corrupto o dañado"
            logger.warning("No se pudo descomprimir RAR (%s): %s", job_id, reason[:180])
            try:
                await status.edit_text(
                    f"<b>{html.escape(display_name)}</b>\n"
                    "┃ ✗ Error al descomprimir\n"
                    f"┠ Motivo: {html.escape(reason[:250])}\n"
                    "┗ Mode: #Extract | #RAR",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        finally:
            process = state.get("process")
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except Exception:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
            state["process"] = None
            jobs.pop(job_id, None)
            user_jobs.pop(owner, None)
            password_waiters.pop(owner, None)
            await asyncio.to_thread(shutil.rmtree, job_dir, True)
