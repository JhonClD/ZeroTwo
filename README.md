# 🤖 Rikka Bot - Bot de Telegram para Procesamiento de Videos

Bot de Telegram avanzado para procesamiento de videos, descargas y búsqueda de anime. Desarrollado con Pyrogram (MTProto) para soportar archivos de **cualquier tamaño** sin límites.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-2.0+-green.svg)](https://docs.pyrogram.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## ✨ Características

### 📹 Procesamiento de Videos
- **Extraer audio** - Formato MP3 a 192kbps

### 📥 Descargas
- **MEGA** - Usando megatools
- **MediaFire** - Con soporte para aria2c (16 conexiones simultáneas)
- **Sin límites de tamaño** - Descarga archivos de cualquier tamaño

### 🈺 Búsqueda de Anime
- Información completa de cualquier anime
- Imágenes en alta calidad
- Sinopsis traducida al español
- Datos de AniList API

## 📦 Instalación

### Termux (Android)

```bash
# Actualizar paquetes
pkg update -y && pkg upgrade -y

# Instalar dependencias
pkg install git python ffmpeg megatools wget curl aria2 -y

# Clonar repositorio
git clone https://github.com/MINORURAKUEN/Rikka-Bot.git
cd Rikka-Bot

# Instalar dependencias Python
pip install -r requirements.txt

# Configurar token del bot
echo "TU_BOT_TOKEN_AQUI" > ~/.telegram_bot_token

# Ejecutar bot
python main.py
```

### Ubuntu/Debian

```bash
# Instalar dependencias
sudo apt update
sudo apt install python3 python3-pip ffmpeg megatools wget curl aria2 -y

# Clonar repositorio
git clone https://github.com/MINORURAKUEN/Rikka-Bot.git
cd Rikka-Bot

# Instalar dependencias Python
pip3 install -r requirements.txt

# Configurar token del bot
echo "TU_BOT_TOKEN_AQUI" > ~/.telegram_bot_token

# Ejecutar bot
python3 main.py
```

## 🔧 Configuración

1. Crear un bot en [@BotFather](https://t.me/BotFather)
2. Copiar el token del bot
3. Guardar el token en `~/.telegram_bot_token`

```bash
echo "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz" > ~/.telegram_bot_token
```

## 📖 Comandos

### Procesamiento de Videos

| Comando | Descripción |
|---------|-------------|
| `/extract_audio` | Extraer audio de un video |

### Descargas

| Comando | Descripción |
|---------|-------------|
| `/download` | Descargar de MEGA o MediaFire |
| Pegar enlace | Descarga automática |

### Búsqueda

| Comando | Descripción |
|---------|-------------|
| `/anime <nombre>` | Buscar información de anime |

### General

| Comando | Descripción |
|---------|-------------|
| `/start` | Iniciar el bot |
| `/help` | Mostrar ayuda detallada |

## 📊 Formatos Soportados

### Videos

### Descargas
- **MEGA**: mega.nz, mega.co.nz
- **MediaFire**: mediafire.com

## 🎨 Características Especiales

### Descargas Optimizadas
```
🚀 aria2c - 16 conexiones (hasta 10x más rápido)
📥 wget - Con reintentos automáticos
📡 curl - Fallback confiable
```

## 📁 Estructura del Proyecto

```
Rikka-Bot/
├── main.py                 # Archivo principal
├── requirements.txt        # Dependencias Python
├── README.md              # Documentación
├── handlers/              # Manejadores de comandos
│   ├── start_handler.py
│   ├── anime_handler.py
│   └── ...
├── utils/                 # Utilidades
│   └── video_processor.py
└── downloaders/           # Descargadores
    ├── mega_downloader.py
    └── mediafire_downloader.py
```

## 🔒 Seguridad

- El token del bot se guarda en `~/.telegram_bot_token` fuera del repositorio
- Los archivos temporales se eliminan automáticamente
- Sin almacenamiento permanente de datos de usuarios

## 🐛 Solución de Problemas

### Error: "megatools not found"
```bash
pkg install megatools  # Termux
sudo apt install megatools  # Ubuntu/Debian
```

### Error: "FFmpeg not found"
```bash
pkg install ffmpeg  # Termux
sudo apt install ffmpeg  # Ubuntu/Debian
```

### Descargas lentas de MediaFire
```bash
pkg install aria2  # Instalar aria2c para descargas 10x más rápidas
```

## 🌐 Descargas sociales

Las descargas de YouTube intentan primero el flujo público de `loader.to` y consultan su progreso hasta obtener el enlace final. Facebook prioriza `fdownloader.net/es`, después `fdown.net/es`, mantiene `loader.to` como respaldo y finalmente prueba APIs públicas. Los sitios pueden cambiar sus endpoints, usar verificación anti-bot o limitar solicitudes; el bot informa el error y no guarda credenciales privadas en el repositorio.

## 📝 Logs

Los logs se guardan automáticamente en:
- `bot.log` - Archivo de registro
- Terminal - Salida en tiempo real

## 🤝 Contribuir

¡Las contribuciones son bienvenidas!

1. Fork el proyecto
2. Crea una rama (`git checkout -b feature/NuevaCaracteristica`)
3. Commit tus cambios (`git commit -m 'Agregar nueva característica'`)
4. Push a la rama (`git push origin feature/NuevaCaracteristica`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto está bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

## 👤 Autor

**MINORURAKUEN**
- GitHub: [@MINORURAKUEN](https://github.com/MINORURAKUEN)
- Telegram: [@MINORURAKUEN](https://t.me/MINORURAKUEN)

## 🙏 Agradecimientos

- [Pyrogram](https://docs.pyrogram.org/) - Framework de Telegram
- [FFmpeg](https://ffmpeg.org/) - Procesamiento de videos
- [AniList](https://anilist.co/) - API de anime

## 📊 Changelog

### v2.0.0 (2026-03-21)
- ✨ Migración a Pyrogram (sin límite de tamaño)
- 🚀 Soporte aria2c para descargas rápidas
- 🈺 Búsqueda de anime con AniList
- 📊 Progreso detallado en terminal
- 🐛 Múltiples correcciones de bugs

### v1.0.0 (2026-03-15)
- 🎉 Lanzamiento inicial
- 📥 Descargas MEGA/MediaFire

---

⭐ Si te gusta este proyecto, dale una estrella en GitHub!
