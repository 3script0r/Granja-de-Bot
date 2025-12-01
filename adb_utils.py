# adb_utils.py
import subprocess
import shlex

# Configuración (modifica si adb/scrcpy no están en PATH)
ADB_PATH = "adb"

def run_adb_cmd_raw(cmd_list):
    """Ejecuta comando (lista) y devuelve stdout, stderr, rc"""
    try:
        p = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return p.stdout, p.stderr, p.returncode
    except FileNotFoundError as e:
        return "", str(e), 127

def run_adb_command(serial, command):
    """
    Ejecuta un comando ADB para un dispositivo específico.
    `command` es la parte después de adb -s <serial>
    Ej: "shell pm list packages"
    """
    # shlex.split para respetar comillas si vienen
    parts = shlex.split(command)
    full = [ADB_PATH, "-s", serial] + parts
    out, err, rc = run_adb_cmd_raw(full)
    if rc != 0:
        # intentar sin -s si falla (fallback)
        out2, err2, rc2 = run_adb_cmd_raw([ADB_PATH] + parts)
        return out2 if out2 else err2
    return out

def list_devices():
    """Lista dispositivos con adb devices"""
    out, err, rc = run_adb_cmd_raw([ADB_PATH, "devices"])
    devices = []
    if out:
        for line in out.strip().splitlines()[1:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
    return devices

def dump_ui_xml(serial, log_cb=None):
    """Extrae el XML de la UI y lo muestra en logs"""
    try:
        # Try multiple paths
        paths = [
            "/sdcard/ui.xml",
            "/data/local/tmp/ui.xml",
            "/storage/emulated/0/ui.xml"
        ]
        
        for path in paths:
            if log_cb:
                log_cb(f"[{serial}] Intentando dump en: {path}")
            
            out, err, rc = run_adb_cmd_raw([ADB_PATH, "-s", serial, "shell", "uiautomator", "dump", path])
            
            if rc == 0:
                if log_cb:
                    log_cb(f"[{serial}] ✅ Dump exitoso en {path}")
                
                # Leer el contenido
                content_out, content_err, content_rc = run_adb_cmd_raw([ADB_PATH, "-s", serial, "shell", "cat", path])
                
                if content_rc == 0 and content_out:
                    if log_cb:
                        log_cb(f"[{serial}] Contenido XML:")
                        # Mostrar solo las primeras líneas para no saturar
                        lines = content_out.split('\n')
                        for line in lines[:20]:  # Primeras 20 líneas
                            if any(keyword in line.lower() for keyword in ['edittext', 'search', 'text', 'id=']):
                                log_cb(f"[{serial}] {line.strip()}")
                    
                    # Limpiar
                    run_adb_cmd_raw([ADB_PATH, "-s", serial, "shell", "rm", path])
                    return True
                
        if log_cb:
            log_cb(f"[{serial}] ❌ No se pudo extraer el XML")
        return False
            
    except Exception as e:
        if log_cb:
            log_cb(f"[{serial}] ERROR en dump_ui_xml: {e}")
        return False