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
- [Instalación en hosting Linux](INSTALACION_HOSTING.md)
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
| Descargas | Descargar archivos de MEGA, MediaFire, enlaces públicos de Google Drive, Drime y GoFile; seleccionar archivos de carpetas públicas de Drive, Drime y GoFile. Las descargas de archivos se procesan en una cola FIFO para evitar ejecuciones simultáneas. |
| Vista previa | En videos descargados desde MEGA, MediaFire o Drive, enviar 10 capturas aleatorias distribuidas durante todo el video antes del video. |
| Anime | Descarga de episodios por URL o búsqueda en VerAnimes, Evangelion-EC, AnimeAV1, Katanime, TioAnime, LatAnime, JKAnime, AnimeDBS y MonosChinos. |
| Utilidades web | Descargar recursos por URL y generar capturas de páginas. |
| Audio | Extraer audio de videos de YouTube. |
| Archivos | Extraer archivos `.rar` con progreso, solicitud temporal de contraseña y cancelación. Los videos se envían como videos reproducibles con duración y miniatura cuando FFmpeg está disponible; los demás archivos se envían como documentos. Se requiere `unrar`, `unar`, `7zz` o `7z` en el sistema. |
| Descargas sociales | YouTube con búsqueda y descarga mediante Loader.to (audio MP3 con carátula cuando está disponible y video hasta 720p); muestra título, canal e imagen antes de descargar. También enlaces públicos de Facebook, X/Twitter y TikTok. |
| Notificaciones | Avisos de episodios recientes de Crunchyroll con miniaturas y enlaces oficiales cuando están disponibles; no descarga videos. |
| Anime | Buscar información, imágenes, sinopsis y datos de AniList. |
| Almacenamiento | Subir archivos a Google Drive mediante OAuth (opcional) o guardarlos en una carpeta compartida de Android. |
| Rendimiento | Usar aria2c cuando está disponible; los torrents descargan un aria2c portable si el hosting no lo trae. |

En Linux, si no existe `megadl`, el descargador de MEGA puede usar una compilación portable oficial de Megatools (x86_64/ARM64), con verificación de integridad y sin permisos root. Consulta la [guía de hosting](INSTALACION_HOSTING.md#1-preparar-el-entorno) para conocer sus requisitos de red y almacenamiento.

Para torrents en Linux, si no existe `aria2c`, ZeroTwo prepara automáticamente una compilación estática de aria2 1.37.0 para x86_64/ARM64/ARMv7, valida los hashes SHA-256 del archivo y del ejecutable y la guarda bajo `.runtime/`, sin permisos root. El binario proviene del [proyecto comunitario aria2-static-build](https://github.com/abcfy2/aria2-static-build/releases/tag/1.37.0); el hosting necesita HTTPS saliente a GitHub y permiso para ejecutar archivos del proyecto. Esto no evita restricciones del proveedor sobre tráfico BitTorrent.

GoFile admite enlaces públicos `https://gofile.io/d/ID`: los enlaces de un solo archivo se descargan directamente y las carpetas muestran un selector para elegir un archivo. No hace falta una cuenta personal ni una API key; el bot crea una cuenta invitada anónima sin correo y reutiliza su token mientras está en ejecución. El tamaño máximo por archivo es 1800 MB por defecto y se puede ajustar con `ZERO_TWO_GOFILE_MAX_MB` (50–4096 MB). GoFile puede cambiar su token web o bloquear IPs de hosting, por lo que el acceso desde BotKeep no se puede garantizar si el proveedor bloquea esas conexiones.

Los enlaces públicos de Drive a **archivos individuales** siguen descargándose sin API ni credenciales. Si pegas una **carpeta**, el bot requiere `GOOGLE_DRIVE_API_KEY` para enumerar sus archivos y muestra un botón por elemento, además de **Descargar todo**. La descarga total respeta por defecto un máximo de 50 archivos, 1800 MB por archivo y 4096 MB sumados; se puede ajustar con `ZERO_TWO_DRIVE_FOLDER_MAX_FILES` (1–200), `ZERO_TWO_DRIVE_MAX_MB` (50–4096) y `ZERO_TWO_DRIVE_ALL_MAX_MB` (100–16384). Los archivos nativos de Google Docs/Sheets/Slides no se incluyen en el selector.

## Requisitos

Antes de instalar el proyecto, necesitas lo siguiente:

| Requisito | Termux | PC |
| --- | --- | --- |
| Python | `python` desde Termux | Python 3.9 o superior |
| Git | `git` desde Termux | Git |
| FFmpeg/FFprobe | `ffmpeg` | FFmpeg |
| Extracción RAR | `unrar`, `unar`, `7zz` o `7z` | `unrar`, `unar`, `7zz` o `7z` |
| Descargas MEGA | `megatools` | Megatools; en Windows se recomienda WSL |
| Torrents/descargas rápidas | `aria2` | aria2 opcional; en Linux, `/torrent` prepara un ejecutable portable si falta |
| YouTube | Loader.to; FFmpeg/FFprobe | Loader.to; FFmpeg/FFprobe |
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
pkg install -y python ffmpeg megatools wget curl aria2 p7zip
python -m pip install -r requirements.txt
python main.py
```

## Instalación manual en Termux

Si prefieres controlar cada paso, utiliza este procedimiento:

```bash
pkg update -y && pkg upgrade -y
pkg install -y git python ffmpeg megatools wget curl aria2 p7zip

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
sudo apt install -y git python3 python3-venv python3-pip ffmpeg megatools wget curl aria2 p7zip-full

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

## API de anime y MyAnimeList

El comando `/anime` utiliza una cadena de fuentes para evitar que una caída temporal deje inutilizada la búsqueda: **AniList**, la **API oficial de MyAnimeList** si se configura `MAL_CLIENT_ID`, **Tenrai** como fuente pública normalizada de datos de MAL, **Jikan** como respaldo adicional y **Kitsu** como último respaldo.

Para activar la API oficial de MyAnimeList, crea una aplicación desde la [configuración de API de tu perfil de MAL](https://myanimelist.net/editprofile.php), copia el Client ID y expórtalo antes de iniciar el bot:

```bash
export MAL_CLIENT_ID="TU_CLIENT_ID_DE_MYANIMELIST"
python main.py
```

La búsqueda no requiere esta variable para funcionar: si no está definida, el bot continúa automáticamente con Tenrai y Jikan. AniList puede devolver un `403` cuando el propio servicio suspende temporalmente la API por problemas de estabilidad; en ese caso el bot no se bloquea y pasa a las fuentes de respaldo.

La instalación base no incluye las librerías de Google Drive, porque `/drive_sync` funciona sin ellas y algunas versiones recientes de Python en Termux pueden intentar compilar `cryptography`. Si necesitas `/gdrive_upload`, instálalas aparte:

```bash
python -m pip install -r requirements-google.txt
```

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

Las descargas de archivos compartidos como **Cualquier persona con el enlace** usan HTTP directo y no requieren API, credenciales ni servicios de Google. El listado de archivos dentro de una carpeta pública sí usa una API key de Google Drive; esto no es OAuth y no concede acceso a carpetas privadas. Los archivos privados o restringidos no se pueden descargar sin autenticación. Los videos públicos descargados reciben la misma vista previa de capturas que los videos de MEGA y MediaFire.

### Descargar carpetas públicas

1. En [Google Cloud Console](https://console.cloud.google.com/), selecciona un proyecto y habilita **Google Drive API**.
2. Crea una **API key** desde APIs y servicios → Credenciales. Restringe la clave a Google Drive API y, si el hosting tiene una IP saliente fija, considera también restringirla a esa IP.
3. Guarda la clave como variable de entorno `GOOGLE_DRIVE_API_KEY` en el panel o en el entorno donde arranca el bot. No la pegues en Telegram, en el repositorio ni en registros.

Pega el enlace de una carpeta pública con acceso **Cualquier persona con el enlace (Lector)**. El bot mostrará una opción por archivo y un botón **Descargar todo**. Solo las carpetas ofrecen el selector; los enlaces a archivos individuales mantienen la descarga directa sin API key. Las claves de API no sirven para saltar permisos ni descargar contenido privado.

OAuth/API se necesita para la **subida directa** de archivos a tu Google Drive. Como alternativa de subida sin API, ZeroTwo puede guardar archivos en el almacenamiento compartido de Android para que una aplicación de sincronización los transfiera.

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

### Sin API de Google

Puedes descargar enlaces públicos de Drive directamente con `/gdrive <enlace>` sin configurar nada en Google Cloud. Para guardar archivos en una carpeta de Termux sin subirlos directamente, habilita el almacenamiento compartido y utiliza `/drive_sync`:

```bash
termux-setup-storage
mkdir -p "$HOME/storage/shared/Download/ZeroTwo"
python main.py
```

En Telegram, envía `/drive_sync` y después el archivo. ZeroTwo lo guardará en `Download/ZeroTwo`; una aplicación de sincronización, como FolderSync, puede transferir esa carpeta a Google Drive. Esta modalidad no requiere `drive_credentials.json`, `drive_token.json` ni credenciales de Google.

## Comandos migrados desde anime-dl

- `/animedl <url>` o `/animedl <nombre> <episodio>` descarga episodios de anime.
- `/hdl <nombre> <episodio>` descarga desde HentaiLA.
- `/get <url>` descarga recursos HTTP/HTTPS de hasta 200 MB.
- `/ssweb <url>` genera una captura de página.

Las credenciales opcionales deben configurarse mediante variables de entorno; no se guardan tokens en el código.

## Comandos disponibles

| Comando o acción | Descripción |
| --- | --- |
| `/start` | Inicia el bot. |
| `/help` | Muestra la ayuda detallada. |
| `/download` | Inicia una descarga desde MEGA o MediaFire. |
| `/gdrive <enlace_o_id>` | Descarga un archivo público de Drive sin API; para carpetas públicas muestra el selector y requiere `GOOGLE_DRIVE_API_KEY`. |
| Enlace público de Drime | Pégalo directamente; descarga el archivo compartido o permite elegir uno dentro de una carpeta. No requiere token API. |
| `/gdrive_upload [folder_id]` | Sube el siguiente archivo a Google Drive mediante OAuth. |
| `/drive_sync` | Guarda el siguiente archivo en la carpeta compartida de Android. |
| `/process` | Responde a un video para elegir compresión o quemar subtítulos. |
| `/compress` | Abre perfiles de compresión; `/compress 700` intenta aproximarse a 700 MB mediante dos pasadas. |
| `/subtitles` o `/sub` | Quema una pista de texto interna o un `.srt`, `.ass`, `.ssa` o `.vtt` enviado al bot. |
| `/processstatus`, `/cancelprocess` | Consulta o cancela tu trabajo de procesamiento. |
| Enviar una foto | La guarda como tu única miniatura personal; una foto nueva reemplaza la anterior. |
| `/show_cover`, `/del_cover` | Mostrar o borrar tu miniatura personal. Los videos siguientes se reenvían con ella. |
| `/thumon`, `/thumoff` | Activar o desactivar la aplicación automática de tu miniatura. Está activa por defecto; la elección persiste por usuario. |
| `/torrent` | Responde a un archivo `.torrent` para descargarlo; pega los enlaces `magnet:` directamente. En Linux puede preparar aria2c portable si no está instalado. |
| `/unrar <nombre.rar>` | Extrae un RAR guardado en la carpeta de descargas. También puedes responder a un documento `.rar` con `/unrar`. Los archivos protegidos solicitan la contraseña por 60 segundos; la respuesta se elimina cuando es posible. Cada archivo extraído se devuelve al chat. |
| `/cancel <ID>` | Cancela una extracción RAR activa usando el ID mostrado en su estado. |
| `/crset`, `/crrem` | Suscribir o quitar el chat de los avisos de Crunchyroll; solo propietario. |
| `/crstatus`, `/crlist`, `/crnotify` | Ver el estado, listar episodios recientes o revisar avisos manualmente. |
| `/anime <nombre>` | Busca información de un anime. |
| Pegar un enlace | Inicia la descarga automática cuando el formato es compatible. |

Drime acepta enlaces compartidos de archivos y carpetas en `app.drime.cloud` con descarga habilitada. Los enlaces a un archivo se descargan directamente; si el enlace es una carpeta, ZeroTwo muestra botones para elegir los archivos de uno en uno. El límite predeterminado es 1800 MB por archivo y se puede ajustar con `ZERO_TWO_DRIME_MAX_MB` (50–4096 MB). El hosting necesita espacio temporal suficiente porque el archivo se descarga primero y luego se envía a Telegram. La integración usa las rutas públicas que consume la web de Drime; Drime podría modificarlas sin aviso.

El procesamiento multimedia usa FFmpeg/FFprobe del entorno. La compresión normal usa una pasada CRF; un tamaño objetivo se aproxima con dos pasadas y consume más CPU. Quemar subtítulos requiere que FFmpeg incluya el filtro `subtitles` (libass). Por defecto se procesa un video a la vez y se admiten hasta dos trabajos entre activos y en cola. Se puede ajustar en el hosting con `ZERO_TWO_VIDEO_WORKERS` (1–2), `ZERO_TWO_VIDEO_QUEUE` (1–6), `ZERO_TWO_VIDEO_MAX_MB` (por defecto 1800 MB), `ZERO_TWO_FFMPEG_THREADS` (1–8) y `ZERO_TWO_FFMPEG_TIMEOUT` (segundos, por defecto 7200). Los archivos de trabajo se eliminan tras completar, cancelar o fallar.

La función de portada guarda por usuario solo el `file_id` de Telegram en `~/telegram_bot_files/video_covers/covers.json`; la preferencia de activación queda en `settings.json`. Está activa por defecto para preservar el comportamiento esperado. Usa `/thumoff` para desactivarla y `/thumon` para reactivarla. Para videos enviados como video normal, usa la Bot API oficial `sendVideo` con los `file_id` tanto del video como de la portada: Telegram reutiliza los archivos en sus servidores, por lo que el bot no descarga ni vuelve a subir el MP4. Si se envía como documento/archivo, Telegram no permite cambiar su tipo al reutilizar el `file_id`; ese caso usa el fallback de descarga y reenvío con `thumb`, requiere FFmpeg y espacio temporal (límite por defecto 1800 MB, ajustable con `ZERO_TWO_COVER_MAX_MB`). La portada cambia la miniatura que muestra Telegram, no los fotogramas del video.

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

### `/unrar` indica que no hay extractor RAR

Instala `unrar`, `unar`, `7zz` o `7z` y verifica que el comando quede disponible en el `PATH`. En Termux usa `pkg install p7zip`; en Debian Trixie instala `unar` con `sudo apt install unar`. El paquete `unrar` está en el componente `non-free`; si `apt` no lo encuentra, usa `unar` desde `main` o habilita ese componente en las fuentes de Debian.

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
