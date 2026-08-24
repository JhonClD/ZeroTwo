# Handlers

Esta carpeta contiene los manejadores de comandos y descargas de ZeroTwo. Cada módulo exporta una función `register(app, ...)` para registrar sus filtros de Pyrogram.

## Módulos activos

| Módulo | Función |
|---|---|
| `start_handler.py` | Comando `/start` |
| `help_handler.py` | Comando `/help` |
| `download_handler.py` | Descargas generales |
| `anime_handler.py` | Búsqueda de anime |
| `youtube_handler.py` | Descargas de YouTube |
| `facebook_handler.py` | Descargas de Facebook mediante loader.to |
| `twitter_handler.py` | Descargas de Twitter/X |
| `tiktok_handler.py` | Descargas de TikTok |
| `url_handler.py` | Descargas desde enlaces de MEGA, MediaFire y Drive |
| `drive_handler.py` | Operaciones de Google Drive |
| `enhance_handler.py` | Mejora de imágenes con IA |
| `tioanime_notify_handler.py` | Notificaciones de episodios |

Las funciones de compresión, encoding, hardsub, subtítulos, miniaturas y extracción de audio fueron retiradas del proyecto. Los videos descargados se envían directamente sin edición multimedia.
