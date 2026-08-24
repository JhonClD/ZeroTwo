#!/usr/bin/env python3
"""
Script de verificación de handlers
Verifica que todos los handlers tengan la función register() correcta
"""

import sys
from pathlib import Path

# Agregar path de handlers
handlers_path = Path(__file__).parent / 'handlers'
sys.path.insert(0, str(handlers_path.parent))

print("🔍 Verificando handlers...\n")

handlers_config = [
    ('start_handler', ['app']),
    ('help_handler', ['app']),
    ('extract_audio_handler', ['app', 'user_states']),
    ('download_handler', ['app']),
    ('anime_handler', ['app', 'user_states', 'work_dir']),
    ('video_handler', ['app', 'user_states', 'work_dir']),
    ('url_handler', ['app', 'download_dir']),
    ('button_callback_handler', ['app', 'user_states', 'work_dir']),
]

all_ok = True

for handler_name, expected_params in handlers_config:
    try:
        # Importar handler
        handler_module = __import__(f'handlers.{handler_name}', fromlist=[handler_name])
        
        # Verificar que tenga la función register
        if not hasattr(handler_module, 'register'):
            print(f"❌ {handler_name}: No tiene función register()")
            all_ok = False
            continue
        
        # Obtener la función
        register_func = getattr(handler_module, 'register')
        
        # Verificar número de parámetros
        import inspect
        sig = inspect.signature(register_func)
        params = list(sig.parameters.keys())
        
        if params == expected_params:
            print(f"✅ {handler_name}: OK - register({', '.join(expected_params)})")
        else:
            print(f"❌ {handler_name}: Parámetros incorrectos")
            print(f"   Esperado: {expected_params}")
            print(f"   Encontrado: {params}")
            all_ok = False
            
    except Exception as e:
        print(f"❌ {handler_name}: Error - {e}")
        all_ok = False

print()
if all_ok:
    print("🎉 ¡Todos los handlers están correctos!")
    sys.exit(0)
else:
    print("⚠️ Hay errores en algunos handlers")
    sys.exit(1)
