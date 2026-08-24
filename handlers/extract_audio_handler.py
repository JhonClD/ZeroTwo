"""
extract_audio_handler.py - Manejador del comando /extract_audio
"""

from pyrogram import filters, enums
from pyrogram.types import Message


def register(app, user_states):
    """Registra el handler del comando /extract_audio"""
    
    @app.on_message(filters.command("extract_audio"))
    async def extract_audio_command(client, message: Message):
        """Comando /extract_audio - Activar modo extraer audio"""
        user_id = message.from_user.id
        user_states[user_id] = {'action': 'extract_audio', 'step': 'waiting_video'}
        
        await message.reply_text(
            "🎵 <b>Modo Extraer Audio Activado</b>\n\n"
            "Envíame el video del que quieres extraer el audio.",
            parse_mode=enums.ParseMode.HTML
        )
