# Handlers

Esta carpeta contiene los manejadores de comandos del bot.

## ⚠️ Nota Importante

Los archivos de handlers individuales deben ser extraídos del archivo completo `telegram_video_bot_pyrogram.py`.

Cada handler debe ser un módulo separado que exporte una función `register(app, ...)`.

## 📋 Handlers Pendientes de Modularizar

- `start_handler.py` - Comando /start
- `help_handler.py` - Comando /help
- `extract_audio_handler.py` - Comando /extract_audio
- `download_handler.py` - Comando /download
- `anime_handler.py` - Comando /anime
- `video_handler.py` - Handler para videos
- `url_handler.py` - Handler para URLs
- `button_callback_handler.py` - Handler para botones inline

## 🔨 Ejemplo de Estructura

```python
# start_handler.py
from pyrogram import filters
from pyrogram.types import Message

def register(app):
    @app.on_message(filters.command("start"))
    async def start_command(client, message: Message):
        await message.reply_text("¡Hola! Soy Rikka Bot")
```

## 📝 Tarea

Separar cada handler del archivo monolítico `telegram_video_bot_pyrogram.py` en archivos individuales siguiendo la estructura de ejemplo.
