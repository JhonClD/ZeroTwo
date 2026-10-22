"""
start_handler.py - Manejador silencioso del comando /start
"""

from pyrogram import filters
from pyrogram.types import Message


def register(app):
    """Registra el handler del comando /start sin enviar ningún mensaje."""

    @app.on_message(filters.command("start"))
    async def start_command(client, message: Message):
        """Ignora /start intencionalmente."""
        return
