"""Actualización segura del checkout ZeroTwo desde el comando del propietario."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from pyrogram import filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)
REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_UPDATE_OWNER_IDS = {7856571519}


def _owner_ids() -> set[int]:
    raw = os.getenv("ZERO_TWO_UPDATE_OWNER_IDS", "") or os.getenv("TIOANIME_OWNER_IDS", "")
    configured = {int(value.strip()) for value in raw.split(",") if value.strip().isdigit()}
    return DEFAULT_UPDATE_OWNER_IDS | configured


def _progress_bar(percent: int, width: int = 13) -> str:
    filled = round(width * percent / 100)
    return "▰" * filled + "▱" * (width - filled)


def _elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _status_card(
    *,
    percent: int,
    branch: str,
    status: str,
    commits: str,
    files: str,
    started: float,
) -> str:
    return (
        "⬡ Update · ZeroTwo\n"
        f"{_progress_bar(percent)} {percent:.2f}%\n\n"
        f"⎇ Branch: {branch}\n"
        f"◈ Status: {status}\n"
        f"⇣ Commits: {commits}\n"
        f"✎ Files: {files}\n"
        f"⏱ Elapsed: {_elapsed(time.monotonic() - started)}"
    )


def _failure_reason(stderr: str, return_code: int) -> str:
    detail = stderr.lower()
    if any(word in detail for word in ("authentication failed", "permission denied", "could not read username", "invalid username", "401", "403")):
        return "credenciales de GitHub inválidas o sin permiso"
    if any(word in detail for word in ("conflict", "not possible to fast-forward", "non-fast-forward", "divergent branches")):
        return "conflicto de Git; no se hizo ningún merge automático"
    if any(word in detail for word in ("could not resolve host", "failed to connect", "connection timed out", "network is unreachable", "could not contact")):
        return "sin conexión con GitHub"
    return f"Git terminó con error (código {return_code})"


async def _git(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(REPO_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError("timeout")
    return (
        process.returncode or 0,
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


async def _edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except Exception:
        logger.debug("No se pudo actualizar la tarjeta de /uptadezero", exc_info=True)


def register(app) -> None:
    @app.on_message(filters.command(["updatezero", "uptadezero"]))
    async def update_zero(client, message: Message):
        owners = _owner_ids()
        sender = message.from_user
        if not owners or not sender or sender.id not in owners:
            await message.reply_text("⛔ Este comando solo está disponible para los propietarios autorizados.")
            return

        started = time.monotonic()
        branch = "desconocida"
        commits_text = "—"
        files_text = "—"
        card = await message.reply_text(_status_card(
            percent=5, branch=branch, status="Verificando repositorio...",
            commits=commits_text, files=files_text, started=started,
        ))

        try:
            code, branch, stderr = await _git("rev-parse", "--abbrev-ref", "HEAD")
            if code != 0:
                raise RuntimeError("checkout")
            if branch != "main":
                raise ValueError("branch")

            code, local_changes, stderr = await _git("status", "--porcelain")
            if code != 0:
                raise RuntimeError("checkout")
            if local_changes:
                raise ValueError("local_changes")

            await _edit(card, _status_card(
                percent=20, branch=branch, status="Consultando GitHub...",
                commits=commits_text, files=files_text, started=started,
            ))
            code, _, stderr = await _git("fetch", "--quiet", "origin", "main", timeout=90)
            if code != 0:
                raise RuntimeError(_failure_reason(stderr, code))

            code, commit_count, stderr = await _git("rev-list", "--count", "HEAD..FETCH_HEAD")
            if code != 0:
                raise RuntimeError(_failure_reason(stderr, code))
            count = int(commit_count or "0")
            code, changed_files, stderr = await _git("diff", "--name-only", "HEAD..FETCH_HEAD")
            if code != 0:
                raise RuntimeError(_failure_reason(stderr, code))
            file_count = len([line for line in changed_files.splitlines() if line.strip()])
            commits_text = f"{count} nuevos" if count else "0 nuevos"
            files_text = f"{file_count} cambiados" if count else "0 cambiados"

            await _edit(card, _status_card(
                percent=46, branch=branch, status="Actualizando...",
                commits=commits_text, files=files_text, started=started,
            ))
            code, _, stderr = await _git("pull", "--ff-only", "--quiet", "origin", "main", timeout=120)
            if code != 0:
                raise RuntimeError(_failure_reason(stderr, code))

            code, commit, stderr = await _git("rev-parse", "--short", "HEAD")
            if code != 0:
                raise RuntimeError(_failure_reason(stderr, code))
            elapsed = _elapsed(time.monotonic() - started)
            if count == 0:
                result = (
                    "⬡ Update · ZeroTwo\n"
                    "✔ Ya está actualizado\n\n"
                    f"⎇ Branch: {branch}\n"
                    f"⌗ Commit: {commit}\n"
                    f"⏱ Elapsed: {elapsed}\n\n"
                    "Sin cambios."
                )
            else:
                result = _status_card(
                    percent=100, branch=branch, status="Actualización completada",
                    commits=commits_text, files=files_text, started=started,
                ) + f"\n⌗ Commit: {commit}"
            await _edit(card, result)
        except ValueError as error:
            if str(error) == "branch":
                reason = "el bot no está en la rama main"
            elif str(error) == "local_changes":
                reason = "hay cambios locales; confirma o guarda esos cambios antes de actualizar"
            else:
                reason = "checkout local no válido"
            await _edit(card, f"⬡ Update · ZeroTwo\n✖ Error al actualizar\n\n⎇ Branch: {branch}\n⚠ Motivo: {reason}\n⏱ Elapsed: {_elapsed(time.monotonic() - started)}")
        except TimeoutError:
            await _edit(card, f"⬡ Update · ZeroTwo\n✖ Error al actualizar\n\n⎇ Branch: {branch}\n⚠ Motivo: GitHub tardó demasiado en responder\n⏱ Elapsed: {_elapsed(time.monotonic() - started)}")
        except RuntimeError as error:
            reason = str(error) if str(error) != "checkout" else "no se pudo verificar el checkout local"
            await _edit(card, f"⬡ Update · ZeroTwo\n✖ Error al actualizar\n\n⎇ Branch: {branch}\n⚠ Motivo: {reason}\n⏱ Elapsed: {_elapsed(time.monotonic() - started)}")
        except Exception:
            logger.exception("Falló /uptadezero")
            await _edit(card, f"⬡ Update · ZeroTwo\n✖ Error al actualizar\n\n⎇ Branch: {branch}\n⚠ Motivo: error inesperado; revisa el registro del bot\n⏱ Elapsed: {_elapsed(time.monotonic() - started)}")
