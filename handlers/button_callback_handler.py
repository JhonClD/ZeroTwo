"""
button_callback_handler.py - Manejador de callbacks mejorado
Soporte para: Compresión, Selección de Audio, Subtítulos y Subdrips con Banderas.
"""

import asyncio
import logging
import os
from pathlib import Path
from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from utils import VideoProcessor

logger = logging.getLogger(__name__)

def register(app, user_states, work_dir):
    """Registra el handler de callbacks de botones"""
    
    @app.on_callback_query()
    async def button_callback(client, callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        data = callback_query.data
        
        if user_id not in user_states:
            await callback_query.answer("⚠️ Sesión expirada. Envía el video de nuevo.", show_alert=True)
            return
        
        state = user_states[user_id]
        video_path = state.get('video_path')

        # --- SECCIÓN: NAVEGACIÓN DE PISTAS (MKV/AVI/ISO) ---
        
        # 1. Listar Audios (Muestra banderas e idiomas)
        if data == "list_audio":
            tracks = VideoProcessor.probe_media(video_path)
            if not tracks['audio']:
                await callback_query.answer("❌ No se encontraron pistas de audio.", show_alert=True)
                return
                
            btns = [
                [InlineKeyboardButton(a['label'], callback_data=f"set_a_{a['index']}")] 
                for a in tracks['audio']
            ]
            btns.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_main")])
            await callback_query.edit_message_reply_markup(InlineKeyboardMarkup(btns))
            return

        # 2. Listar Subtítulos (Muestra banderas e índices corregidos)
        if data == "list_sub":
            tracks = VideoProcessor.probe_media(video_path)
            if not tracks['subtitle']:
                await callback_query.answer("❌ No se encontraron subtítulos internos.", show_alert=True)
                return

            btns = [
                [InlineKeyboardButton(s['label'], callback_data=f"set_s_{s['index']}")] 
                for s in tracks['subtitle']
            ]
            btns.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_main")])
            await callback_query.edit_message_reply_markup(InlineKeyboardMarkup(btns))
            return

        # 3. Guardar selección de Audio
        if data.startswith("set_a_"):
            state['selected_audio'] = data.split("_")[-1]
            await callback_query.answer("🔊 Audio seleccionado correctamente")
            return

        # 4. Guardar selección de Subtítulo
        if data.startswith("set_s_"):
            state['selected_sub'] = data.split("_")[-1]
            await callback_query.answer("📝 Subtítulo/Subdrip seleccionado correctamente")
            return

        # 5. Volver al menú principal de quema
        if data == "back_to_main":
            buttons = [
                [InlineKeyboardButton("🔊 Elegir Audio", callback_data="list_audio")],
                [InlineKeyboardButton("📝 Elegir Subtítulo", callback_data="list_sub")],
                [InlineKeyboardButton("🔥 Iniciar Quema", callback_data="start_burn_process")]
            ]
            await callback_query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
            return

        # 6. Ejecutar Quema de Subtítulos (Usa el nuevo estilo visual)
        if data == "start_burn_process":
            if 'selected_sub' not in state:
                await callback_query.answer("⚠️ Selecciona un subtítulo primero", show_alert=True)
                return
            
            await callback_query.message.edit_text(
                "⏳ **Iniciando proceso de quema...**\n"
                "🎨 Estilo: Texto blanco, contorno azul claro.\n"
                "🚀 Esto puede tardar dependiendo del tamaño."
            )
            
            output_burn = work_dir / f"{user_id}_burned.mp4"
            
            success = VideoProcessor.burn_subtitles(
                video_path, str(output_burn),
                audio_idx=state.get('selected_audio'),
                sub_idx=state.get('selected_sub')
            )
            
            if success:
                await callback_query.message.reply_video(
                    video=str(output_burn),
                    caption="✅ **Quema completada exitosamente**\nEstilo visual aplicado."
                )
                output_burn.unlink()
            else:
                await callback_query.message.reply_text("❌ Error crítico al procesar la quema de subtítulos.")
            
            # Limpieza tras quema
            if Path(video_path).exists(): Path(video_path).unlink()
            del user_states[user_id]
            return

        # --- SECCIÓN: COMPRESIÓN (Lógica original) ---

        if data.startswith('format_'):
            format_map = {'format_mp4': '.mp4', 'format_mkv': '.mkv', 'format_avi': '.avi', 'format_webm': '.webm'}
            state['output_format'] = format_map.get(data, '.mp4')
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 360p", callback_data='quality_360p'), InlineKeyboardButton("📺 480p", callback_data='quality_480p')],
                [InlineKeyboardButton("🖥️ 720p HD", callback_data='quality_720p'), InlineKeyboardButton("🎬 1080p Full HD", callback_data='quality_1080p')]
            ])
            await callback_query.message.edit_text("Selecciona la resolución para comprimir:", reply_markup=keyboard)
            return

        if data.startswith('quality_'):
            res_map = {
                'quality_360p': {'scale': '640:360', 'label': '360p'},
                'quality_480p': {'scale': '854:480', 'label': '480p'},
                'quality_720p': {'scale': '1280:720', 'label': '720p HD'},
                'quality_1080p': {'scale': '1920:1080', 'label': '1080p FHD'}
            }
            config = res_map.get(data, res_map['quality_360p'])
            state['scale'] = config['scale']
            state['resolution_label'] = config['label']
            profile_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('📦 Pequeño', callback_data='profile_small'), InlineKeyboardButton('⚖️ Equilibrado', callback_data='profile_balanced')],
                [InlineKeyboardButton('✨ Alta calidad', callback_data='profile_quality'), InlineKeyboardButton('🚀 H.265 / HEVC', callback_data='profile_hevc')],
            ])
            await callback_query.message.edit_text(
                f"Resolución: <b>{config['label']}</b>\n\nSelecciona el perfil de encoding:",
                parse_mode='html', reply_markup=profile_keyboard
            )
            await callback_query.answer()
            return

        if data.startswith('profile_'):
            profile = data.removeprefix('profile_')
            if profile not in VideoProcessor.ENCODING_PROFILES:
                await callback_query.answer('Perfil no disponible.', show_alert=True)
                return
            label = VideoProcessor.ENCODING_PROFILES[profile]['label']
            resolution_label = state.get('resolution_label', 'original')
            extension = state.get('output_format', '.mp4')
            output_path = work_dir / f"{user_id}_comp_{profile}_{resolution_label}{extension}"
            await callback_query.message.edit_text(f"⚙️ Comprimiendo: {resolution_label} · {label}...")
            success = await asyncio.to_thread(
                VideoProcessor.compress_profile,
                video_path, str(output_path), profile=profile, scale=state.get('scale')
            )
            if success:
                caption = f"✅ Video comprimido\n🎞 {resolution_label}\n🎛 Perfil: {label}"
                if extension.lower() == '.mp4':
                    thumb_path = work_dir / f"{user_id}_comp_thumb.jpg"
                    duration, thumb = VideoProcessor.get_video_meta(output_path, thumb_path)
                    await callback_query.message.reply_video(
                        video=str(output_path), caption=caption,
                        supports_streaming=True, duration=duration or None, thumb=thumb
                    )
                    thumb_path.unlink(missing_ok=True)
                else:
                    await callback_query.message.reply_document(document=str(output_path), caption=caption)
                output_path.unlink(missing_ok=True)
            else:
                await callback_query.message.reply_text('❌ No se pudo completar la compresión.')
            if Path(video_path).exists():
                Path(video_path).unlink()
            del user_states[user_id]
            await callback_query.answer()
            return

