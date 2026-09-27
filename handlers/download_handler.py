"""
download_handler.py - Manejador del comando /download
"""

from pyrogram import filters, enums
from pyrogram.types import Message


def register(app):
    """Registra el handler del comando /download"""
    
    @app.on_message(filters.command("download"))
    async def download_command(client, message: Message):
        """Comando /download - Instrucciones de descarga"""
        await message.reply_text(
            "📥 <b>Modo Descarga Activado</b>\n\n"
            "Envíame un enlace de:\n"
            "🔷 MEGA (mega.nz)\n"
            "🔶 MediaFire (mediafire.com)\n\n"
            "Ejemplo:\n"
            "<code>https://mega.nz/file/abc123#xyz789</code>",
            parse_mode=enums.ParseMode.HTML
        )
