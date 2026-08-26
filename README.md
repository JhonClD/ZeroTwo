# ZeroTwo

Bot de Telegram para descargar, procesar y enviar videos, además de consultar información de anime. El proyecto utiliza [Pyrogram](https://docs.pyrogram.org/) y herramientas del sistema como FFmpeg, Megatools y aria2.

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-2.x-2CA5E0)](https://docs.pyrogram.org/)
[![Licencia](https://img.shields.io/badge/licencia-MIT-green.svg)](LICENSE)

## Contenido

- [Características](#características)
- [Requisitos](#requisitos)
- [Instalación rápida en Termux](#instalación-rápida-en-termux-android)
- [Instalación manual en Termux](#instalación-manual-en-termux)
- [Instalación en PC](#instalación-en-pc)
- [Configuración del token](#configuración-del-token)
- [Ejecución y actualización](#ejecución-y-actualización)
- [Google Drive](#google-drive-opcional)
- [Comandos](#comandos-disponibles)
- [Solución de problemas](#solución-de-problemas)
- [Seguridad](#seguridad)
- [Contribuir](#contribuir)

## Características

ZeroTwo ofrece las siguientes funciones principales:

| Área | Función |
| --- | --- |
| Telegram | Recibir enlaces y archivos mediante un bot. |
| Descargas | Descargar contenido de MEGA y MediaFire. |
| Procesamiento | Extraer audio en MP3 y procesar videos con FFmpeg. |
| Descargas sociales | Flujo público para enlaces de YouTube, Facebook, X/Twitter y TikTok. |
| Anime | Buscar información, imágenes, sinopsis y datos de AniList. |
| Almacenamiento | Subir archivos a Google Drive mediante OAuth o guardarlos en una carpeta compartida de Android. |
| Rendimiento | Usar aria2c cuando está disponible y wget/curl como alternativas. |

## Requisitos

Antes de instalar el proyecto, necesitas lo siguiente:

| Requisito | Termux | PC |
| --- | --- | --- |
| Python | `python` desde Termux | Python 3.8 o superior |
| Git | `git` desde Termux | Git |
| FFmpeg/FFprobe | `ffmpeg` | FFmpeg |
| Descargas MEGA | `megatools` | Megatools; en Windows se recomienda WSL |
| Descargas rápidas | `aria2` | aria2; opcional pero recomendado |
| Credenciales | Token creado con [@BotFather](https://t.me/BotFather) | Token creado con [@BotFather](https://t.me/BotFather) |

El bot necesita acceso a Internet mientras está en ejecución. En Termux, se recomienda utilizar una versión actualizada instalada desde [F-Droid](https://f-droid.org/packages/com.termux/) o desde la fuente oficial de Termux; no mezcles paquetes de instalaciones diferentes.

## Instalación rápida en Termux (Android)

Este es el método recomendado para una instalación nueva. Abre Termux y ejecuta los comandos siguientes:

```bash
pkg update -y && pkg upgrade -y
pkg install -y git

git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo

chmod +x install_termux.sh
./install_termux.sh
```

El instalador instala Python y las herramientas externas, instala las dependencias de `requirements.txt` y solicita el token del bot. Al terminar, inicia ZeroTwo con:

```bash
python main.py
```

Si ya tienes el repositorio descargado y solo necesitas repetir la instalación, ejecuta desde la carpeta del proyecto:

```bash
pkg update -y
pkg install -y python ffmpeg megatools wget curl aria2
python -m pip install -r requirements.txt
python main.py
```

## Instalación manual en Termux

Si prefieres controlar cada paso, utiliza este procedimiento:

```bash
pkg update -y && pkg upgrade -y
pkg install -y git python ffmpeg megatools wget curl aria2

git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Después, configura el token y ejecuta el bot:

```bash
printf '%s\n' 'TU_TOKEN_DEL_BOT' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
python main.py
```

### Acceso al almacenamiento de Android

Esta configuración solo es necesaria si vas a utilizar `/drive_sync` para guardar archivos en una carpeta accesible desde Android:

```bash
termux-setup-storage
mkdir -p "$HOME/storage/shared/Download/ZeroTwo"
python main.py
```

Concede el permiso cuando Android lo solicite. La ruta predeterminada es `Download/ZeroTwo`. Puedes cambiarla antes de iniciar el bot:

```bash
export ZERO_TWO_SYNC_DIR="$HOME/storage/shared/Download/MiCarpeta"
python main.py
```

## Instalación en PC

### Linux: Ubuntu o Debian

Instala las herramientas del sistema, clona el proyecto y crea un entorno virtual para no mezclar sus dependencias con las del sistema:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg megatools wget curl aria2

git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Configura el token y arranca el bot:

```bash
printf '%s\n' 'TU_TOKEN_DEL_BOT' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
python main.py
```

Cada vez que vuelvas a abrir una terminal, activa el entorno virtual antes de ejecutar el bot:

```bash
cd ZeroTwo
source .venv/bin/activate
python main.py
```

### Windows

En Windows, instala [Git](https://git-scm.com/download/win), [Python](https://www.python.org/downloads/windows/) y [FFmpeg](https://ffmpeg.org/download.html). Durante la instalación de Python, activa la opción **Add Python to PATH**. Añade las carpetas de `ffmpeg` y `aria2` al `PATH` de Windows para que el comando `ffmpeg`, `ffprobe` y `aria2c` estén disponibles desde PowerShell.

Para una experiencia más compatible con las herramientas de Linux, la opción recomendada es utilizar **WSL2 con Ubuntu** y seguir la sección [Linux: Ubuntu o Debian](#linux-ubuntu-o-debian). Si instalas directamente en Windows, ejecuta en PowerShell:

```powershell
git clone https://github.com/JhonClD/ZeroTwo.git
Set-Location ZeroTwo

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Guarda el token en el archivo que espera el programa y ejecuta el bot:

```powershell
Set-Content -Path "$HOME\.telegram_bot_token" -Value "TU_TOKEN_DEL_BOT"
python main.py
```

Si PowerShell impide activar el entorno virtual, puedes permitir scripts para tu usuario y repetir la activación:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

En Windows, verifica las herramientas con:

```powershell
python --version
ffmpeg -version
ffprobe -version
aria2c -v
```

`megatools` no siempre está disponible como paquete nativo para Windows. Si `/download` necesita descargar desde MEGA, utiliza WSL2 o instala una compilación compatible y asegúrate de que `megadl.exe` esté en el `PATH`.

### macOS

Instala [Homebrew](https://brew.sh/) y las herramientas externas:

```bash
brew install git python ffmpeg megatools wget curl aria2

git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
printf '%s\n' 'TU_TOKEN_DEL_BOT' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
python main.py
```

## Configuración del token

Crea el bot con [@BotFather](https://t.me/BotFather), copia el token que te entregue Telegram y guárdalo en `~/.telegram_bot_token`. Sustituye el texto de ejemplo por tu token real:

```bash
printf '%s\n' '1234567890:ABCdefGHIjklMNOpqrsTUVwxyz' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
```

No publiques este archivo, no lo incluyas en capturas de pantalla y no lo escribas directamente dentro del código. Si el token se filtra, revócalo y genera uno nuevo desde BotFather.

## Ejecución y actualización

Para detener el bot, pulsa `Ctrl+C`. Los registros se muestran en la terminal y también se guardan en `bot.log`.

Para actualizar una instalación existente:

```bash
cd ZeroTwo
git pull
```

En Linux, macOS o Windows con entorno virtual activo, actualiza también las dependencias:

```bash
python -m pip install -r requirements.txt
```

En Termux, utiliza `python` en lugar de `python3` si ambos comandos no apuntan a la misma instalación.

## Google Drive (opcional)

ZeroTwo admite dos formas de guardar archivos en Google Drive. La primera utiliza la API oficial de Google Drive con OAuth 2.0; la segunda guarda el archivo en el almacenamiento compartido de Android para que una aplicación de sincronización lo transfiera.

### API oficial de Google Drive

1. En [Google Cloud Console](https://console.cloud.google.com/), crea o selecciona un proyecto y habilita **Google Drive API**.
2. Configura la pantalla de consentimiento OAuth y crea credenciales de tipo **Desktop app**.
3. Descarga el JSON y guárdalo exactamente como `downloaders/drive_credentials.json`.
4. Inicia ZeroTwo y utiliza `/gdrive_upload`. La primera autorización generará `downloaders/drive_token.json`.
5. Envía un documento, imagen, video o audio después del comando para subirlo a Drive.

Para seleccionar una carpeta predeterminada, define su ID antes de iniciar el bot:

```bash
export GOOGLE_DRIVE_FOLDER_ID="ID_DE_LA_CARPETA"
python main.py
```

También puedes indicar una carpeta para una subida concreta:

```text
/gdrive_upload ID_DE_LA_CARPETA
```

### Sin configurar la API de Google

En Termux, habilita el almacenamiento compartido y utiliza `/drive_sync`:

```bash
termux-setup-storage
mkdir -p "$HOME/storage/shared/Download/ZeroTwo"
python main.py
```

En Telegram, envía `/drive_sync` y después el archivo. ZeroTwo lo guardará en `Download/ZeroTwo`; una aplicación de sincronización, como FolderSync, puede transferir esa carpeta a Google Drive. Esta modalidad no requiere `drive_credentials.json`, `drive_token.json` ni credenciales de Google.

## Comandos disponibles

| Comando o acción | Descripción |
| --- | --- |
| `/start` | Inicia el bot. |
| `/help` | Muestra la ayuda detallada. |
| `/download` | Inicia una descarga desde MEGA o MediaFire. |
| `/gdrive_upload [folder_id]` | Sube el siguiente archivo a Google Drive mediante OAuth. |
| `/drive_sync` | Guarda el siguiente archivo en la carpeta compartida de Android. |
| `/anime <nombre>` | Busca información de un anime. |
| Pegar un enlace | Inicia la descarga automática cuando el formato es compatible. |

## Solución de problemas

### `No se encontró el archivo ~/.telegram_bot_token`

Crea el archivo en la misma cuenta de usuario con la que ejecutas el bot:

```bash
printf '%s\n' 'TU_TOKEN_DEL_BOT' > "$HOME/.telegram_bot_token"
chmod 600 "$HOME/.telegram_bot_token"
```

### `ffmpeg`, `ffprobe` o `megadl` no están disponibles

Comprueba si los comandos están en el `PATH`:

```bash
command -v ffmpeg
command -v ffprobe
command -v megadl
```

En Termux, reinstálalos con `pkg install -y ffmpeg megatools`. En Ubuntu/Debian, utiliza `sudo apt install -y ffmpeg megatools`. En Windows, revisa el `PATH` o utiliza WSL2.

### `pip` rechaza la instalación

Usa el módulo de Python correspondiente y, en PC, un entorno virtual:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

En Ubuntu/Debian, si `python` no existe, usa `python3` para crear el entorno: `python3 -m venv .venv`.

### Termux no puede acceder a `storage/shared`

Ejecuta `termux-setup-storage`, acepta el permiso de Android y verifica la ruta con:

```bash
ls -la "$HOME/storage/shared"
```

### Las descargas de MediaFire son lentas

Confirma que `aria2c` está instalado. El bot lo utiliza cuando el servidor y el tipo de descarga lo permiten; si no está disponible, puede recurrir a wget o curl.

## Estructura del proyecto

```text
ZeroTwo/
├── main.py                 # Punto de entrada del bot
├── requirements.txt        # Dependencias Python
├── install_termux.sh       # Instalador automático para Termux
├── handlers/               # Manejadores de comandos
├── downloaders/            # Descargadores e integración con Drive
├── utils/                  # Procesamiento y utilidades
├── README.md               # Documentación
└── LICENSE                 # Licencia MIT
```

## Seguridad

El token se guarda fuera del repositorio, en `~/.telegram_bot_token`. Las credenciales OAuth de Google Drive (`downloaders/drive_credentials.json` y `downloaders/drive_token.json`) están excluidas de Git y nunca deben compartirse. Tampoco se deben publicar archivos `.session`, registros ni enlaces privados.

Los archivos de trabajo se guardan en `telegram_bot_files/` y `telegram_downloads/`; los registros se escriben en `bot.log`. Estos archivos están excluidos del control de versiones mediante `.gitignore`.

## Contribuir

Las contribuciones son bienvenidas. Crea una rama descriptiva, realiza cambios pequeños y verificables, prueba la instalación en el sistema correspondiente y abre un Pull Request:

```bash
git checkout -b mejora-readme
git add README.md
git commit -m "Mejorar instrucciones de instalación"
git push origin mejora-readme
```

## Licencia

Este proyecto se distribuye bajo la [Licencia MIT](LICENSE).

## Autor

**MINORURAKUEN**

- GitHub: [@MINORURAKUEN](https://github.com/MINORURAKUEN)
- Telegram: [@MINORURAKUEN](https://t.me/MINORURAKUEN)

## Referencias

[1]: https://docs.pyrogram.org/ "Documentación oficial de Pyrogram"
[2]: https://termux.dev/ "Sitio oficial de Termux"
[3]: https://wiki.termux.com/wiki/Termux-setup-storage "Documentación de almacenamiento compartido en Termux"
[4]: https://ffmpeg.org/ "Sitio oficial de FFmpeg"
[5]: https://developers.google.com/workspace/drive/api/quickstart/python "Inicio rápido de Google Drive API para Python"

---

Si te gusta el proyecto, puedes darle una estrella en GitHub.
