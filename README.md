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

### Google Drive: guardar archivos enviados desde Telegram

ZeroTwo incluye un modo para recibir un archivo en Telegram y subirlo a Google Drive. La integración usa la API oficial de Google Drive con OAuth 2.0 y carga reanudable para archivos grandes ([guía de autenticación](https://developers.google.com/workspace/drive/api/quickstart/python), [guía de subidas](https://developers.google.com/workspace/drive/api/guides/manage-uploads)).

1. En [Google Cloud Console](https://console.cloud.google.com/), crea o selecciona un proyecto y habilita **Google Drive API**.
2. Configura la pantalla de consentimiento OAuth y crea un cliente OAuth de tipo **Desktop app**.
3. Descarga el JSON de credenciales y guárdalo exactamente como `downloaders/drive_credentials.json`.
4. Inicia ZeroTwo. La primera vez que uses Drive, Google abrirá el proceso de autorización; al finalizar se creará `downloaders/drive_token.json`.
5. En el chat del bot envía `/gdrive_upload` y después envía un documento, foto, video o audio. ZeroTwo lo subirá a **Mi unidad** y responderá con el enlace.

Para usar siempre una carpeta específica, copia su ID desde la URL de Drive y define la variable antes de iniciar el bot:

```bash
export GOOGLE_DRIVE_FOLDER_ID="ID_DE_LA_CARPETA"
python main.py
```

También puedes elegir una carpeta solamente para una subida concreta:

```text
/gdrive_upload ID_DE_LA_CARPETA
```

Los archivos `drive_credentials.json` y `drive_token.json` están excluidos de Git. No los subas al repositorio ni compartas su contenido.

## 📖 Comandos

### Descargas

| Comando | Descripción |
|---------|-------------|
| `/download` | Descargar de MEGA o MediaFire |
| `/gdrive_upload [folder_id]` | Activar la subida del siguiente archivo a Google Drive |
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
- Las credenciales OAuth de Drive se guardan en `downloaders/drive_credentials.json` y `downloaders/drive_token.json`, ambos excluidos de Git
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

Las descargas de YouTube y Facebook utilizan exclusivamente el flujo público de `loader.to` y consultan su progreso hasta obtener el enlace final. En Facebook, el bot consulta las calidades disponibles, las muestra mediante botones y descarga la opción elegida; si loader.to no devuelve calidades, utiliza 720p como valor predeterminado. El servicio puede cambiar sus endpoints o limitar solicitudes; el bot informa el error y no guarda credenciales privadas en el repositorio.

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
- [Google Drive API](https://developers.google.com/workspace/drive/api) - Integración de almacenamiento

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
