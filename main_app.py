# main_app.py
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import os
import threading
import time
from adb_utils import list_devices, run_adb_command
from script_executor import execute_script_for_device
from visual_editor import VisualFlowEditor
import subprocess
# Configuración (modifica si adb/scrcpy no están en PATH)
SCRCPY_PATH = "scrcpy"

class AndroidMultiControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Android Multi-Control — scrcpy + adb + UIAutomator2")
        self.root.geometry("1250x820")

        self.devices = []
        self.profiles = {}

        self.create_widgets()
        self.refresh_devices()

    def create_widgets(self):
        # left frame devices & actions
        left = tk.Frame(self.root)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)

        tk.Label(left, text="Dispositivos conectados:").pack()
        self.device_listbox = tk.Listbox(left, selectmode=tk.MULTIPLE, width=36, height=20)
        self.device_listbox.pack()
        tk.Button(left, text="🔄 Refresh Devices", command=self.refresh_devices).pack(pady=4)
        tk.Button(left, text="📱 Abrir scrcpy (screen off)", command=self.open_scrcpy_selected).pack(pady=4)
        tk.Button(left, text="🧭 Open Visual Editor", command=self.open_visual_editor).pack(pady=4)

        # middle: command & run
        mid = tk.Frame(self.root)
        mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        tk.Label(mid, text="ADB command (sin 'adb -s <device>')").pack()
        self.command_entry = tk.Entry(mid, width=90)
        self.command_entry.pack(pady=4)
        tk.Button(mid, text="▶ Send Command to selected", command=self.send_command_selected).pack(pady=4)

        tk.Button(mid, text="▶ Run Script on selected (open file)", command=self.run_script_on_selected).pack(pady=4)
        tk.Button(mid, text="📂 Save/Load Profile (script + devices)", command=self.profile_dialog).pack(pady=4)
        tk.Button(mid, text="📂 Open Template (save)", command=self.open_template).pack(pady=4)

        tk.Label(mid, text="Editor JSON (visual export/import)").pack(pady=(8,0))
        self.script_text = tk.Text(mid, height=15)
        self.script_text.pack(fill=tk.BOTH, expand=True, pady=6)
        tk.Button(mid, text="▶ Ejecutar JSON del editor en seleccionados", command=self.run_inline_json).pack(pady=4)

        # right: log
        right = tk.Frame(self.root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, padx=6, pady=6)
        tk.Label(right, text="Log:").pack()
        self.log_text = tk.Text(right, height=30, width=60)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        ts = time.strftime("%H:%M:%S")
        try:
            self.log_text.insert(tk.END, f"[{ts}] {text}\n")
            self.log_text.see(tk.END)
        except:
            pass
        print(f"[{ts}] {text}")

    def refresh_devices(self):
        self.devices = list_devices()
        self.device_listbox.delete(0, tk.END)
        for d in self.devices:
            self.device_listbox.insert(tk.END, d)
        self.log(f"Found devices: {self.devices}")

    def get_selected_devices(self):
        indices = self.device_listbox.curselection()
        return [self.device_listbox.get(i) for i in indices]

    def open_scrcpy_selected(self):
        devs = self.get_selected_devices()
        if not devs:
            messagebox.showwarning("Select", "Selecciona uno o más dispositivos")
            return
        for d in devs:
            threading.Thread(target=lambda s=d: subprocess.Popen([SCRCPY_PATH, "-s", s, "--turn-screen-off"]), daemon=True).start()
            self.log(f"Abrir scrcpy para {d}")

    def open_visual_editor(self):
        VisualFlowEditor(self.root, inject_target_textwidget=self.script_text)

    def send_command_selected(self):
        devs = self.get_selected_devices()
        cmd = self.command_entry.get().strip()
        if not cmd:
            messagebox.showwarning("Empty", "Escribe el comando ADB (sin 'adb -s <device>')")
            return
        for d in devs:
            out = run_adb_command(d, cmd)
            self.log(f"[{d}] $ adb {cmd}\n{out}")

    def run_inline_json(self):
        txt = self.script_text.get("1.0", tk.END).strip()
        if not txt:
            messagebox.showwarning("Empty", "No hay JSON en el editor.")
            return
        try:
            script = json.loads(txt)
        except Exception as e:
            messagebox.showerror("JSON inválido", str(e))
            return
        for d in self.get_selected_devices():
            threading.Thread(target=lambda s=d, sc=script: execute_script_for_device(s, sc, log_cb=self.log), daemon=True).start()
            self.log(f"Ejecutando inline JSON en {d}")

    def run_script_on_selected(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Files","*.json")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                script = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer script: {e}")
            return
        devs = self.get_selected_devices()
        if not devs:
            messagebox.showwarning("Select", "Selecciona uno o más dispositivos")
            return
        for d in devs:
            threading.Thread(target=lambda s=d, sc=script: execute_script_for_device(s, sc, log_cb=self.log), daemon=True).start()
            self.log(f"Ejecutando {os.path.basename(path)} en {d}")

    def open_template(self):
        template = {
            "steps":[
                {"action": "start_app", "package": "com.facebook.katana"},
                {"action": "sleep", "seconds": 2},
                {"action": "uia_click", "resourceId": "com.facebook.katana:id/search_edit_text"},
                {"action": "uia_text", "text": "MochilArte"},
                {"action": "keyevent", "key": 66},
                {"action": "sleep", "seconds": 2},
                {"action": "uia_click", "text": "Me gusta"}
            ]
        }
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=4)
            self.log(f"Template saved at {path}")

    def profile_dialog(self):
        # simple save/load profile: store mapping in memory
        choice = simpledialog.askstring("Profile", "choose: save or load")
        if not choice: return
        if choice.lower().startswith("save"):
            name = simpledialog.askstring("Profile Name","Name:")
            if not name: return
            devs = self.get_selected_devices()
            path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
            if not path: return
            self.profiles[name] = [path, devs]
            self.log(f"Profile '{name}' saved.")
        else:
            # load
            if not self.profiles:
                messagebox.showinfo("Profiles", "No hay perfiles guardados en memoria.")
                return
            name = simpledialog.askstring("Profile", f"Name {list(self.profiles.keys())}")
            if not name or name not in self.profiles:
                messagebox.showwarning("Profile", "Profile no encontrado.")
                return
            script_path, devs = self.profiles[name]
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            for d in devs:
                threading.Thread(target=lambda s=d, sc=script: execute_script_for_device(s, sc, log_cb=self.log), daemon=True).start()
                self.log(f"Profile '{name}' executed on {d}")

# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = AndroidMultiControlApp(root)
    root.mainloop()