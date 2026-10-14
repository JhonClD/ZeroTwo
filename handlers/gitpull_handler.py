"""Owner-only command for safely fast-forwarding the bot checkout."""
import asyncio
import logging
from pathlib import Path

from pyrogram import filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)
OWNER_TELEGRAM_ID = 7856571519
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PULL_TIMEOUT_SECONDS = 90


def register(app):
    @app.on_message(filters.command("gitpull"))
    async def gitpull_command(client, message: Message):
        sender = message.from_user
        if sender is None or sender.id != OWNER_TELEGRAM_ID:
            await message.reply_text("⛔ Este comando está reservado al propietario del bot.")
            logger.warning("/gitpull denegado; usuario=%s", getattr(sender, "id", "sin usuario"))
            return

        if len(message.command) != 1:
            await message.reply_text("Uso: /gitpull")
            return

        status = await message.reply_text("⏳ Actualizando desde origin/main…")
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "-C", str(PROJECT_ROOT), "pull", "--ff-only", "origin", "main",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            _, _ = await asyncio.wait_for(
                process.communicate(), timeout=PULL_TIMEOUT_SECONDS
            )
        except FileNotFoundError:
            await status.edit_text("❌ Git no está instalado o no está disponible en PATH del hosting.")
            return
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            await status.edit_text("⏱️ La actualización tardó demasiado. Revisa Git y la conexión del hosting.")
            return
        except Exception:
            logger.exception("Error ejecutando /gitpull")
            await status.edit_text("❌ No se pudo ejecutar la actualización. Revisa los registros del hosting.")
            return

        if process.returncode == 0:
            await status.edit_text(
                "✅ git pull --ff-only terminó correctamente.\n\n"
                "Para aplicar cambios al proceso que ya está corriendo, reinicia el bot desde el panel."
            )
            logger.info("/gitpull completado por el propietario")
        else:
            logger.error("/gitpull falló con código de salida %s", process.returncode)
            await status.edit_text(
                "❌ No se pudo actualizar con git pull --ff-only.\n"
                "Comprueba que el hosting tenga Git, una copia clonada del repositorio y acceso a origin/main."
            )
