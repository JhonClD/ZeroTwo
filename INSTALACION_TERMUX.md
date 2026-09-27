# 🚀 GUÍA DE INSTALACIÓN COMPLETA - TERMUX

## 📱 Requisitos Previos

- ✅ Android 7.0 o superior
- ✅ Termux instalado desde F-Droid (NO desde Play Store)
- ✅ Conexión a Internet
- ✅ ~500 MB de espacio libre
- ✅ Token de bot de Telegram (obtener en @BotFather)

---

## 📥 MÉTODO 1: Instalación Automática (Recomendado)

### Paso 1: Actualizar Termux
```bash
pkg update -y && pkg upgrade -y
```

### Paso 2: Instalar Git
```bash
pkg install git -y
```

### Paso 3: Clonar el Repositorio
```bash
cd ~
git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo
```

### Paso 4: Ejecutar Script de Instalación
```bash
chmod +x install_termux.sh
./install_termux.sh
```

El script instalará automáticamente:
- ✅ Python
- ✅ FFmpeg
- ✅ Megatools
- ✅ Wget
- ✅ Curl
- ✅ Aria2c
- ✅ Pyrogram
- ✅ TgCrypto

### Paso 5: Iniciar el Bot
```bash
python main.py
```

---

## 🔧 MÉTODO 2: Instalación Manual

### Paso 1: Actualizar Termux
```bash
pkg update -y && pkg upgrade -y
```

### Paso 2: Instalar Dependencias del Sistema
```bash
pkg install -y \
  git \
  python \
  ffmpeg \
  megatools \
  wget \
  curl \
  aria2
```

**Tiempo estimado:** 5-10 minutos

### Paso 3: Verificar Instalación de Herramientas
```bash
python --version      # Debe mostrar Python 3.x
ffmpeg -version       # Debe mostrar FFmpeg
megadl --version      # Debe mostrar megatools
wget --version        # Debe mostrar Wget
curl --version        # Debe mostrar Curl
aria2c --version      # Debe mostrar aria2c
```

### Paso 4: Actualizar pip
```bash
pip install --upgrade pip
```

### Paso 5: Clonar el Repositorio
```bash
cd ~
git clone https://github.com/JhonClD/ZeroTwo.git
cd ZeroTwo
```

### Paso 6: Instalar Dependencias Python
```bash
pip install -r requirements.txt
```

Esto instalará:
- ✅ `pyrogram>=2.0.0` - Cliente de Telegram
- ✅ `tgcrypto` - Aceleración de cifrado
- ✅ `Pillow` - Portadas visuales de `/anime`

Las librerías de Google Drive son opcionales. Solo si vas a usar `/gdrive_upload`, instala también:

```bash
pip install -r requirements-google.txt
```

### Paso 7: Configurar Token del Bot

#### Opción A: Crear archivo manualmente
```bash
echo "TU_BOT_TOKEN_AQUI" > ~/.telegram_bot_token
```

#### Opción B: Usar editor nano
```bash
nano ~/.telegram_bot_token
```
- Pega tu token
- Presiona `Ctrl + X`
- Presiona `Y`
- Presiona `Enter`

**Ejemplo de token:**
```
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Paso 8: Verificar Configuración
```bash
cat ~/.telegram_bot_token
```

Debe mostrar tu token completo.

### Paso 9: Dar Permisos (Opcional)
```bash
chmod +x main.py
chmod 600 ~/.telegram_bot_token  # Solo tú puedes leerlo
```

### Paso 10: Iniciar el Bot
```bash
python main.py
```

---

## 📋 Verificación de Instalación

Al iniciar el bot, deberías ver:

```
╔══════════════════════════════════════════╗
║  🤖 BOT DE TELEGRAM - PROCESAMIENTO DE VIDEOS  ║
╚══════════════════════════════════════════╝
🔧 Versión: Pyrogram (Sin límite de tamaño)
📁 Directorio de trabajo: /data/data/com.termux/files/home/telegram_bot_files
📥 Directorio de descargas: /data/data/com.termux/files/home/telegram_downloads
📝 Log guardado en: bot.log
══════════════════════════════════════════
🔍 Verificando herramientas necesarias...
✅ FFmpeg: Instalado
✅ FFprobe: Instalado
✅ Megatools: Instalado
✅ Wget: Instalado
══════════════════════════════════════════
🚀 Bot iniciado correctamente
⏸️ Presiona Ctrl+C para detener
══════════════════════════════════════════
```

---

## 🎯 Obtener Token del Bot

### Paso 1: Abrir @BotFather en Telegram
```
https://t.me/BotFather
```

### Paso 2: Crear Nuevo Bot
```
/newbot
```

### Paso 3: Seguir Instrucciones
1. **Nombre del bot** (ej: "Mi Bot de Videos")
2. **Username del bot** (ej: "mi_video_bot")
   - Debe terminar en "bot"
   - Debe ser único

### Paso 4: Copiar Token
BotFather te dará un token como:
```
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Paso 5: Guardar Token en Termux
```bash
echo "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz" > ~/.telegram_bot_token
```

---

## 🔄 Mantener el Bot Funcionando

### Opción 1: Ejecutar en Primer Plano
```bash
python main.py
```
- ✅ Ves los logs en tiempo real
- ❌ Termux debe estar abierto

### Opción 2: Ejecutar en Segundo Plano con nohup
```bash
nohup python main.py > bot_output.log 2>&1 &
```
- ✅ Termux puede cerrarse
- ✅ Logs guardados en `bot_output.log`

**Ver logs en tiempo real:**
```bash
tail -f bot_output.log
```

**Detener el bot:**
```bash
pkill -f main.py
```

### Opción 3: Usar tmux (Recomendado)
```bash
# Instalar tmux
pkg install tmux -y

# Crear sesión
tmux new -s bot

# Dentro de tmux, ejecutar el bot
python main.py

# Salir de tmux (bot sigue corriendo)
# Presiona: Ctrl+B, luego D

# Volver a la sesión
tmux attach -t bot

# Detener sesión
tmux kill-session -t bot
```

---

## 🐛 Solución de Problemas

### Error: "pkg: command not found"
**Solución:** Reinstala Termux desde F-Droid (NO desde Play Store)

### Error: "python: command not found"
```bash
pkg install python -y
```

### Error: "FFmpeg not found"
```bash
pkg install ffmpeg -y
```

### Error: "megatools not found"
```bash
pkg install megatools -y
```

### Error: "No module named 'pyrogram'"
```bash
pip install pyrogram tgcrypto
```

### Error: "Permission denied" al ejecutar script
```bash
chmod +x install_termux.sh
chmod +x main.py
```

### Error: "Invalid token format"
**Verifica:**
1. Token copiado completo (sin espacios)
2. Formato: `números:letras`
3. Archivo `~/.telegram_bot_token` existe

```bash
cat ~/.telegram_bot_token  # Verificar contenido
```

### Bot se detiene cuando cierro Termux
**Solución:** Usa tmux o nohup (ver sección "Mantener el Bot Funcionando")

### Descargas lentas de MediaFire
```bash
# Instalar aria2c para descargas 10x más rápidas
pkg install aria2 -y
```

### Error: "Disk quota exceeded"
**Liberar espacio:**
```bash
# Ver espacio usado
du -sh ~/ZeroTwo

# Limpiar archivos temporales
rm -rf ~/telegram_bot_files/*
rm -rf ~/telegram_downloads/*

# Limpiar cache de pip
pip cache purge
```

---

## 🔄 Actualizar el Bot

```bash
cd ~/ZeroTwo

# Detener el bot (si está corriendo)
pkill -f main.py

# Actualizar desde GitHub
git pull

# Reinstalar dependencias (por si acaso)
pip install -r requirements.txt

# Iniciar de nuevo
python main.py
```

---

## 📊 Uso de Recursos

| Recurso | Uso Aproximado |
|---------|----------------|
| **Espacio en disco** | ~500 MB (instalación completa) |
| **RAM** | ~100-200 MB (bot corriendo) |
| **CPU** | Bajo (excepto al procesar videos) |
| **Batería** | Moderado (mantener Termux abierto) |

---

## 💡 Consejos

### 1. Mantener Termux Activo
Para evitar que Android mate el proceso:
- Desactiva optimización de batería para Termux
- Activa "Ejecutar en segundo plano" en los permisos

### 2. Logs
```bash
# Ver logs en tiempo real
tail -f bot.log

# Ver últimas 50 líneas
tail -n 50 bot.log

# Buscar errores
grep ERROR bot.log
```

### 3. Reinicio Automático
Crear script de auto-reinicio:
```bash
nano restart_bot.sh
```

Contenido:
```bash
#!/bin/bash
while true; do
    python ~/ZeroTwo/main.py
    echo "Bot detenido. Reiniciando en 5 segundos..."
    sleep 5
done
```

Ejecutar:
```bash
chmod +x restart_bot.sh
./restart_bot.sh
```

---

## 📞 Soporte

¿Problemas? Contacta:
- **GitHub Issues:** https://github.com/JhonClD/ZeroTwo/issues
- **Telegram:** @MINORURAKUEN

---

## ✅ Checklist de Instalación

- [ ] Termux instalado desde F-Droid
- [ ] Paquetes actualizados (`pkg update && pkg upgrade`)
- [ ] Git instalado
- [ ] Python instalado
- [ ] FFmpeg instalado
- [ ] Megatools instalado
- [ ] Wget instalado
- [ ] Curl instalado
- [ ] Aria2c instalado
- [ ] Repositorio clonado
- [ ] Dependencias Python instaladas
- [ ] Token del bot configurado en `~/.telegram_bot_token`
- [ ] Bot ejecutándose correctamente

---

🎉 **¡Listo! Tu bot está funcionando en Termux.**

**Siguiente paso:** Envía `/start` a tu bot en Telegram para probarlo.
