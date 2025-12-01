# visual_editor.py
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import threading
import time
import subprocess
from adb_utils import list_devices, run_adb_cmd_raw
from script_executor import execute_script_for_device

class VisualFlowEditor(tk.Toplevel):
    BLOCK_W = 160
    BLOCK_H = 56

    PALETTE = [
        {"type": "start", "label": "Start"},
        {"type": "start_app", "label": "Abrir App"},
        {"type": "open_link", "label": "Abrir Link"},
        {"type": "tap", "label": "Tap (coords)"},
        {"type": "text", "label": "Escribir texto"},
        {"type": "swipe", "label": "Swipe"},
        {"type": "sleep", "label": "Esperar"},
        {"type": "set_var", "label": "Variable ="},
        {"type": "increment_var", "label": "Variable++"},
        {"type": "decrement_var", "label": "Variable--"},
        {"type": "math_operation", "label": "Operación Math"},
        {"type": "if", "label": "If (cond)"},
        {"type": "while", "label": "While (loop)"},
        {"type": "break", "label": "Break"},
        {"type": "continue", "label": "Continue"},
        {"type": "uia_click", "label": "UIA Click"},
        {"type": "uia_text", "label": "UIA Escribir"},
        {"type": "stop", "label": "Stop"},
    ]
    
    def __init__(self, master, inject_target_textwidget=None):
        super().__init__(master)
        self.title("Visual Script Builder — bloques y líneas")
        self.geometry("1200x760")
        self.resizable(True, True)

        self.inject_target = inject_target_textwidget

        # estado
        self.nodes = {}
        self.edges = []  # tuples (from_id, to_id, line_id)
        self.dragging_node_id = None
        self.drag_offset = (0, 0)
        self.connect_mode = False
        self.connect_source_id = None
        self.next_id = 1
        
        # selección persistente
        self.selected_node = None   # id como "n3"
        self.selected_edge = None   # canvas item id (línea)

        # drag-drop from palette helpers
        self.dragging_palette_item = None
        self.temp_preview = None

        self.create_widgets()
        
        # nodos base
        self.add_block("start", "Start", 120, 120)
        self.add_block("stop", "Stop", 900, 120)

    def create_widgets(self):
        # layout
        left = tk.Frame(self, width=260)
        left.pack(side=tk.LEFT, fill=tk.Y)
        right = tk.Frame(self)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # palette
        tk.Label(left, text="Paleta de acciones", font=("Segoe UI", 12, "bold")).pack(pady=(8,6))
        self.palette_frame = tk.Frame(left)
        self.palette_frame.pack(fill=tk.X, padx=6)
        for item in self.PALETTE:
            lbl = tk.Label(self.palette_frame, text=f"{item['label']}", relief=tk.RAISED, bd=1, padx=6, pady=4, bg="#e6eef6")
            lbl.pack(fill=tk.X, pady=4)
            # bind click-to-add
            lbl.bind("<Button-1>", lambda e, it=item: self.add_block(item_type=it["type"], label=it["label"], x=320, y=120))
            # bind drag start
            lbl.bind("<ButtonPress-3>", lambda e, it=item: self.start_palette_drag(it, e))
            lbl.bind("<B3-Motion>", self.palette_drag_motion)
            lbl.bind("<ButtonRelease-3>", self.palette_drop)

        tk.Label(left, text="(click para agregar • click-derecho y arrastrar para drop)", fg="gray").pack(padx=6, pady=(0,8))

        tk.Button(left, text="➕ Agregar bloque seleccionado", command=self.add_block_from_selection).pack(fill=tk.X, padx=8, pady=6)
        tk.Button(left, text="✏️ Editar parámetros", command=self.edit_selected_block).pack(fill=tk.X, padx=8)
        tk.Button(left, text="🗑️ Eliminar bloque", command=self.delete_selected_block).pack(fill=tk.X, padx=8, pady=(4,10))

        tk.Label(left, text="Conexiones", font=("Segoe UI", 11, "bold")).pack(pady=(8,2))
        self.connect_btn = tk.Button(left, text="🔗 Conectar (click origen→destino)", command=self.toggle_connect_mode)
        self.connect_btn.pack(fill=tk.X, padx=8)
        tk.Button(left, text="❌ Borrar conexión", command=self.delete_selected_edge).pack(fill=tk.X, padx=8, pady=4)

        tk.Label(left, text="Exportar", font=("Segoe UI", 11, "bold")).pack(pady=(10,2))
        tk.Button(left, text="💾 Exportar a JSON (al editor)", command=self.export_to_json).pack(fill=tk.X, padx=8)
        tk.Button(left, text="📂 Guardar JSON…", command=self.save_json_file).pack(fill=tk.X, padx=8, pady=(4,10))
        tk.Button(left, text="▶ Ejecutar flujo aquí", command=self.execute_from_editor).pack(fill=tk.X, padx=8, pady=(0,8))

        # canvas
        toolbar = tk.Frame(right)
        toolbar.pack(fill=tk.X)
        tk.Label(toolbar, text="Lienzo: arrastra bloques • doble clic para editar").pack(side=tk.LEFT, padx=8)
        tk.Button(toolbar, text="Centrar inicio", command=lambda: self.canvas.yview_moveto(0)).pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(right, bg="#071020", scrollregion=(0,0,3000,3000))
        self.canvas.pack(fill=tk.BOTH, expand=True)

        vs = tk.Scrollbar(self.canvas.master, orient="vertical", command=self.canvas.yview)
        hs = tk.Scrollbar(self.canvas.master, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)

        # eventos
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def clear_selection(self):
        """Quita resaltado de nodo o arista seleccionada."""
        if self.selected_node:
            n = self.nodes.get(self.selected_node)
            if n:
                try:
                    rect = n["canvas_ids"][0]
                    self.canvas.itemconfig(rect, outline="#38bdf8", width=2)
                except Exception:
                    pass
            self.selected_node = None

        if self.selected_edge:
            try:
                self.canvas.itemconfig(self.selected_edge, fill="#94a3b8", width=2)
            except Exception:
                pass
            self.selected_edge = None

    def select_node(self, nid):
        """Selecciona (y resalta) un nodo por su id."""
        if nid == self.selected_node:
            return
        self.clear_selection()
        if nid in self.nodes:
            self.selected_node = nid
            try:
                rect = self.nodes[nid]["canvas_ids"][0]
                self.canvas.itemconfig(rect, outline="#fb923c", width=3)  # color resaltado
            except Exception:
                pass

    def select_edge(self, lid):
        """Selecciona (y resalta) una línea (edge) por su id."""
        if lid == self.selected_edge:
            return
        self.clear_selection()
        self.selected_edge = lid
        try:
            self.canvas.itemconfig(lid, fill="#fb7185", width=4)
        except Exception:
            pass

    def start_palette_drag(self, item, event):
        self.dragging_palette_item = item
        # show preview rect on canvas
        x = self.winfo_pointerx() - self.canvas.winfo_rootx()
        y = self.winfo_pointery() - self.canvas.winfo_rooty()
        self.temp_preview = self.canvas.create_rectangle(x, y, x+self.BLOCK_W, y+self.BLOCK_H, outline="#ffffff", dash=(4,2))
        self.canvas.update()

    def palette_drag_motion(self, event):
        if self.dragging_palette_item and self.temp_preview:
            x = self.winfo_pointerx() - self.canvas.winfo_rootx()
            y = self.winfo_pointery() - self.canvas.winfo_rooty()
            self.canvas.coords(self.temp_preview, x, y, x+self.BLOCK_W, y+self.BLOCK_H)

    def palette_drop(self, event):
        if not self.dragging_palette_item: return
        x = self.winfo_pointerx() - self.canvas.winfo_rootx()
        y = self.winfo_pointery() - self.canvas.winfo_rooty()
        it = self.dragging_palette_item
        self.add_block(it["type"], it["label"], x, y)
        if self.temp_preview:
            try: self.canvas.delete(self.temp_preview)
            except: pass
        self.temp_preview = None
        self.dragging_palette_item = None

    def add_block_from_selection(self):
        # fallback: add first
        self.add_block("tap", "Tap", 320, 320)

    def add_block(self, item_type, label, x, y):
        nid = f"n{self.next_id}"
        self.next_id += 1
        rect = self.canvas.create_rectangle(x, y, x+self.BLOCK_W, y+self.BLOCK_H,
                                            fill="#0f1720", outline="#38bdf8", width=2, tags=("block", nid))
        text = self.canvas.create_text(x+self.BLOCK_W/2, y+self.BLOCK_H/2, text=label, fill="white", tags=("block", nid))
        out = self.canvas.create_oval(x+self.BLOCK_W-10, y+self.BLOCK_H/2-6, x+self.BLOCK_W-2, y+self.BLOCK_H/2+6,
                                fill="#38bdf8", outline="", tags=("port_out", nid))
        inp = self.canvas.create_oval(x+2, y+self.BLOCK_H/2-6, x+10, y+self.BLOCK_H/2+6,
                                fill="#22c55e", outline="", tags=("port_in", nid))
        self.nodes[nid] = {"type": item_type, "label": label, "x": x, "y": y, "params": {}, "canvas_ids": (rect, text), "ports": (out, inp)}

    def node_at(self, event):
        items = self.canvas.find_withtag("current")
        if items:
            tags = self.canvas.gettags(items[0])
            for t in tags:
                if t.startswith("n"):
                    return t
        # fallback by coords
        x, y = event.x, event.y
        for nid, n in self.nodes.items():
            if n["x"] <= x <= n["x"] + self.BLOCK_W and n["y"] <= y <= n["y"] + self.BLOCK_H:
                return nid
        return None

    def redraw_node(self, nid):
        n = self.nodes[nid]
        x, y = n["x"], n["y"]
        rect, text = n["canvas_ids"]
        self.canvas.coords(rect, x, y, x+self.BLOCK_W, y+self.BLOCK_H)
        self.canvas.coords(text, x+self.BLOCK_W/2, y+self.BLOCK_H/2)
        out_id, in_id = n.get("ports", (None, None))
        if out_id:
            self.canvas.coords(out_id, x+self.BLOCK_W-10, y+self.BLOCK_H/2-6, x+self.BLOCK_W-2, y+self.BLOCK_H/2+6)
        if in_id:
            self.canvas.coords(in_id, x+2, y+self.BLOCK_H/2-6, x+10, y+self.BLOCK_H/2+6)
        # update lines
        for (a,b,lid) in list(self.edges):
            if a==nid or b==nid:
                ax, ay = self.anchor_out(a)
                bx, by = self.anchor_in(b)
                try:
                    self.canvas.coords(lid, ax, ay, bx, by)
                except Exception:
                    pass

    def anchor_out(self, nid):
        n = self.nodes[nid]
        return n["x"] + self.BLOCK_W, n["y"] + self.BLOCK_H/2

    def anchor_in(self, nid):
        n = self.nodes[nid]
        return n["x"], n["y"] + self.BLOCK_H/2

    def on_canvas_click(self, event):
        # detectar item bajo cursor (topmost)
        x, y = event.x, event.y
        items = self.canvas.find_overlapping(x, y, x, y)
        nid = None
        edge_id = None
        if items:
            item = items[-1]  # topmost
            tags = self.canvas.gettags(item)
            for t in tags:
                if t.startswith("n"):
                    nid = t
                if t == "edge":
                    edge_id = item

        if self.connect_mode:
            # Si estamos en modo conectar, usar nodos (no bordes)
            if nid:
                if self.connect_source_id is None:
                    self.connect_source_id = nid
                    self.select_node(nid)
                    return
                if self.connect_source_id and nid and self.connect_source_id != nid:
                    ax, ay = self.anchor_out(self.connect_source_id)
                    bx, by = self.anchor_in(nid)
                    line = self.canvas.create_line(ax, ay, bx, by, fill="#94a3b8", width=2, arrow=tk.LAST, tags=("edge",))
                    self.edges.append((self.connect_source_id, nid, line))
                self.connect_source_id = None
            return

        # si clic en arista -> seleccionar arista
        if edge_id:
            self.select_edge(edge_id)
            return

        # si clic en nodo -> seleccionar + comenzar drag
        if nid:
            self.select_node(nid)
            self.dragging_node_id = nid
            n = self.nodes[nid]
            self.drag_offset = (event.x - n["x"], event.y - n["y"])
        else:
            # clic en vacío -> limpiar selección
            self.clear_selection()

    def on_canvas_double_click(self, event):
        nid = self.node_at(event)
        if not nid: return
        self.edit_block_params(nid)

    def on_canvas_drag(self, event):
        if not self.dragging_node_id: return
        dx, dy = self.drag_offset
        n = self.nodes[self.dragging_node_id]
        n["x"], n["y"] = event.x - dx, event.y - dy
        self.redraw_node(self.dragging_node_id)

    def on_canvas_release(self, _event):
        self.dragging_node_id = None

    def toggle_connect_mode(self):
        self.connect_mode = not self.connect_mode
        self.connect_source_id = None
        self.connect_btn.config(relief=tk.SUNKEN if self.connect_mode else tk.RAISED)

    def selected_node_id(self):
        return self.selected_node

    def edit_selected_block(self):
        nid = self.selected_node_id()
        if nid:
            self.edit_block_params(nid)
        else:
            messagebox.showinfo("Info", "Haz clic sobre un bloque para editarlo.")

    def edit_block_params(self, nid):
        n = self.nodes[nid]
        t = n["type"]

        if t == "open_link":
            url = simpledialog.askstring("Abrir Link", "Ingresa el URL:", initialvalue=n["params"].get("url",""))
            if url:
                n["params"]["url"] = url

        elif t == "start_app":
            pkg = simpledialog.askstring("Abrir App", "Package (ej: com.facebook.katana):", initialvalue=n["params"].get("package",""))
            if pkg: n["params"]["package"] = pkg

        elif t == "tap":
            val = simpledialog.askstring("Tap", "x,y:", initialvalue=f"{n['params'].get('x','')},{n['params'].get('y','')}")
            if val and "," in val:
                try:
                    x,y = [int(v.strip()) for v in val.split(",")]
                    n["params"]["x"]=x; n["params"]["y"]=y
                except:
                    messagebox.showerror("Error","Coordenadas inválidas")

        elif t == "text":
            txt = simpledialog.askstring("Texto", "Texto a escribir:", initialvalue=n["params"].get("text",""))
            if txt is not None: n["params"]["text"]=txt

        elif t == "swipe":
            val = simpledialog.askstring("Swipe", "x1,y1,x2,y2,duration(ms):",
                                         initialvalue=f"{n['params'].get('x1','')},{n['params'].get('y1','')},{n['params'].get('x2','')},{n['params'].get('y2','')},{n['params'].get('duration',300)}")
            try:
                x1,y1,x2,y2,d = [int(v) for v in val.split(",")]
                n["params"].update({"x1":x1,"y1":y1,"x2":x2,"y2":y2,"duration":d})
            except Exception:
                messagebox.showerror("Error","Parametros swipe invalidos")

        elif t == "sleep":
            s = simpledialog.askinteger("Esperar", "Segundos:", initialvalue=n["params"].get("seconds",1), minvalue=0)
            if s is not None: n["params"]["seconds"]=int(s)

        elif t == "set_var":
            name = simpledialog.askstring("Variable", "Nombre de variable:", initialvalue=n["params"].get("name",""))
            val = simpledialog.askstring("Variable", "Valor:", initialvalue=n["params"].get("value",""))
            if name is not None:
                n["params"]["name"]=name
                n["params"]["value"]=val

        elif t == "increment_var":
            name = simpledialog.askstring("Incrementar Variable", "Nombre de variable:", initialvalue=n["params"].get("name",""))
            increment = simpledialog.askinteger("Incrementar Variable", "Valor a incrementar:", initialvalue=n["params"].get("increment",1), minvalue=1)
            if name is not None and increment is not None:
                n["params"]["name"]=name
                n["params"]["increment"]=increment

        elif t == "decrement_var":
            name = simpledialog.askstring("Decrementar Variable", "Nombre de variable:", initialvalue=n["params"].get("name",""))
            decrement = simpledialog.askinteger("Decrementar Variable", "Valor a decrementar:", initialvalue=n["params"].get("decrement",1), minvalue=1)
            if name is not None and decrement is not None:
                n["params"]["name"]=name
                n["params"]["decrement"]=decrement

        elif t == "math_operation":
            name = simpledialog.askstring("Operación Matemática", "Nombre de variable:", initialvalue=n["params"].get("name",""))
            operation = simpledialog.askstring("Operación Matemática", "Operación (ej: +5, -3, *2, /4):", initialvalue=n["params"].get("operation",""))
            if name is not None and operation is not None:
                n["params"]["name"]=name
                n["params"]["operation"]=operation

        elif t == "if":
            # cond_type: 'var_equals', 'var_greater', 'var_less', 'var_exists', 'uia_exists'
            cond_type = simpledialog.askstring("If", "Tipo cond (var_equals/var_greater/var_less/var_exists/uia_exists):", initialvalue=n["params"].get("cond_type","var_equals"))
            
            if cond_type in ["var_equals", "var_greater", "var_less"]:
                name = simpledialog.askstring("If - var", "Nombre variable:", initialvalue=n["params"].get("name",""))
                val = simpledialog.askstring("If - var", "Valor esperado:", initialvalue=n["params"].get("value",""))
                skip = simpledialog.askinteger("If - var", "Cuántos pasos saltar si falso?:", initialvalue=n["params"].get("skip",1), minvalue=0)
                n["params"].update({"cond_type":cond_type,"name":name,"value":val,"skip":skip})
            
            elif cond_type == "var_exists":
                name = simpledialog.askstring("If - var exists", "Nombre variable:", initialvalue=n["params"].get("name",""))
                skip = simpledialog.askinteger("If - var exists", "Cuántos pasos saltar si no existe?:", initialvalue=n["params"].get("skip",1), minvalue=0)
                n["params"].update({"cond_type":"var_exists","name":name,"skip":skip})
            
            elif cond_type == "uia_exists":
                target = simpledialog.askstring("If - uia", "text=... or resourceId=...", initialvalue=n["params"].get("text", n["params"].get("resourceId","")))
                skip = simpledialog.askinteger("If - uia", "Cuántos pasos saltar si no existe?:", initialvalue=n["params"].get("skip",1), minvalue=0)
                # parse quick
                if target and "=" in target:
                    k,v = target.split("=",1)
                    n["params"].update({"cond_type":"uia_exists", k.strip():v.strip(), "skip":skip})
                else:
                    n["params"].update({"cond_type":"uia_exists","text":target,"skip":skip})

        elif t == "while":
            # cond_type: 'var_equals', 'var_greater', 'var_less', 'var_exists', 'uia_exists'
            cond_type = simpledialog.askstring("While", "Tipo cond (var_equals/var_greater/var_less/var_exists/uia_exists):", initialvalue=n["params"].get("cond_type","var_equals"))
            
            if cond_type in ["var_equals", "var_greater", "var_less"]:
                name = simpledialog.askstring("While - var", "Nombre variable:", initialvalue=n["params"].get("name",""))
                val = simpledialog.askstring("While - var", "Valor esperado:", initialvalue=n["params"].get("value",""))
                max_iterations = simpledialog.askinteger("While", "Máximo de iteraciones (0=sin límite):", initialvalue=n["params"].get("max_iterations",0), minvalue=0)
                n["params"].update({"cond_type":cond_type,"name":name,"value":val,"max_iterations":max_iterations})
            
            elif cond_type == "var_exists":
                name = simpledialog.askstring("While - var exists", "Nombre variable:", initialvalue=n["params"].get("name",""))
                max_iterations = simpledialog.askinteger("While", "Máximo de iteraciones (0=sin límite):", initialvalue=n["params"].get("max_iterations",0), minvalue=0)
                n["params"].update({"cond_type":"var_exists","name":name,"max_iterations":max_iterations})
            
            elif cond_type == "uia_exists":
                target = simpledialog.askstring("While - uia", "text=... or resourceId=...", initialvalue=n["params"].get("text", n["params"].get("resourceId","")))
                max_iterations = simpledialog.askinteger("While", "Máximo de iteraciones (0=sin límite):", initialvalue=n["params"].get("max_iterations",0), minvalue=0)
                # parse quick
                if target and "=" in target:
                    k,v = target.split("=",1)
                    n["params"].update({"cond_type":"uia_exists", k.strip():v.strip(), "max_iterations":max_iterations})
                else:
                    n["params"].update({"cond_type":"uia_exists","text":target,"max_iterations":max_iterations})

        elif t == "break":
            # No necesita parámetros adicionales
            pass

        elif t == "continue":
            # No necesita parámetros adicionales
            pass

        elif t == "uia_click":
            val = simpledialog.askstring("UIA Click", "resourceId=... , text=...  (o x,y):", initialvalue=", ".join(f"{k}={v}" for k,v in n["params"].items()))
            if val:
                if "," in val and "=" not in val:
                    try:
                        x,y = [int(v.strip()) for v in val.split(",")]
                        n["params"]["x"]=x; n["params"]["y"]=y
                    except:
                        messagebox.showerror("Error","Coords invalidas")
                else:
                    for token in val.split(","):
                        if "=" in token:
                            k,v = token.split("=",1); n["params"][k.strip()] = v.strip()

        elif t == "uia_text":
            txt = simpledialog.askstring("UIA Escribir", "resourceId=... (opcional) ; text:", initialvalue=n["params"].get("text",""))
            if txt is not None:
                if "resourceId=" in txt or "text=" in txt:
                    parts = [p for p in txt.split(",") if "=" in p]
                    for p in parts:
                        k,v = p.split("=",1); n["params"][k.strip()] = v.strip()
                else:
                    n["params"]["text"] = txt

    def delete_selected_block(self):
        nid = self.selected_node
        if not nid:
            messagebox.showinfo("Info", "Haz clic sobre un bloque para seleccionarlo y eliminarlo.")
            return

        # borrar edges asociados
        for (a, b, lid) in list(self.edges):
            if a == nid or b == nid:
                try:
                    self.canvas.delete(lid)
                except:
                    pass
                try:
                    self.edges.remove((a, b, lid))
                except ValueError:
                    pass

        # borrar items del nodo (rect, text, puertos)
        for item in self.canvas.find_withtag(nid):
            try:
                self.canvas.delete(item)
            except:
                pass

        # eliminar del dict
        self.nodes.pop(nid, None)
        self.selected_node = None

    def delete_selected_edge(self):
        lid = self.selected_edge
        if not lid:
            messagebox.showinfo("Info", "Haz clic sobre una conexión (línea) para seleccionarla y luego pulsa 'Borrar conexión'.")
            return
        for e in list(self.edges):
            if e[2] == lid:
                try:
                    self.canvas.delete(lid)
                except:
                    pass
                try:
                    self.edges.remove(e)
                except ValueError:
                    pass
                break
        self.selected_edge = None

    def topo_sort(self):
        adj = {nid: [] for nid in self.nodes}
        indeg = {nid: 0 for nid in self.nodes}
        for a,b,_ in self.edges:
            if a in adj:
                adj[a].append(b)
                indeg[b] += 1
        starts = [nid for nid,v in self.nodes.items() if v["type"]=="start"] or [nid for nid in self.nodes if indeg[nid]==0]
        order = []
        vis = set()
        def dfs(u):
            if u in vis: return
            vis.add(u); order.append(u)
            for v in adj.get(u,[]): dfs(v)
        for s in starts: dfs(s)
        return order

    def export_to_json(self):
        order = self.topo_sort()
        steps = []
        for nid in order:
            n = self.nodes[nid]
            t = n["type"]
            if t in ("start","stop"): continue
            step = {"action": t}
            step.update(n["params"])
            steps.append(step)
        doc = {"steps": steps}
        if self.inject_target is not None:
            self.inject_target.delete("1.0", tk.END)
            self.inject_target.insert(tk.END, json.dumps(doc, indent=4, ensure_ascii=False))
            messagebox.showinfo("Exportado", "El flujo se volcó al editor JSON de la ventana principal.")
        else:
            messagebox.showinfo("Exportado", json.dumps(doc, indent=2, ensure_ascii=False))

    def save_json_file(self):
        order = self.topo_sort()
        steps = []
        for nid in order:
            n = self.nodes[nid]
            t = n["type"]
            if t in ("start","stop"): continue
            step = {"action": t}
            step.update(n["params"])
            steps.append(step)
        doc = {"steps": steps}
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=4, ensure_ascii=False)
            messagebox.showinfo("Guardado", f"Flujo guardado en:\n{path}")

    def execute_from_editor(self):
        # obtener JSON y ejecutar en dispositivo seleccionado (pedir dispositivo)
        doc = {}
        order = self.topo_sort()
        steps = []
        for nid in order:
            n = self.nodes[nid]
            t = n["type"]
            if t in ("start","stop"): continue
            step = {"action": t}
            step.update(n["params"])
            steps.append(step)
        doc = {"steps": steps}
        # pedir dispositivo
        devices = list_devices()
        if not devices:
            messagebox.showwarning("No devices", "No hay dispositivos conectados.")
            return
        if len(devices) == 1:
            serial = devices[0]
        else:
            serial = simpledialog.askstring("Device", f"Dispositivo (lista: {devices}):")
            if serial not in devices:
                messagebox.showwarning("Device", "Selecciona un dispositivo válido.")
                return
        stop_ev = threading.Event()
        threading.Thread(target=lambda: execute_script_for_device(serial, doc, log_cb=self._log_callback, stop_event=stop_ev), daemon=True).start()

    def _log_callback(self, msg):
        # intenta volcar al inject_target si existe (no ideal), else print
        print(msg)
        if self.inject_target:
            try:
                self.inject_target.insert(tk.END, msg + "\n")
            except:
                pass

    def start_recorder_for_device(self, serial, duration=5):
        """
        Intenta capturar eventos táctiles desde adb getevent -lt y parsear coordenadas.
        Esto es experimental y puede no funcionar en todos los dispositivos.
        """
        cmd = ["adb", "-s", serial, "shell", "getevent", "-lt"]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as e:
            messagebox.showerror("Error", f"adb no encontrado: {e}")
            return

        coords = []
        start = time.time()
        try:
            while True:
                if p.stdout is None:
                    break
                line = p.stdout.readline()
                if not line:
                    break
                line = line.strip()
                # buscar ABS_MT_POSITION_X y ABS_MT_POSITION_Y
                if "ABS_MT_POSITION_X" in line or "ABS_MT_POSITION_Y" in line:
                    # la línea suele tener hex o dec; tomaremos números
                    tokens = line.replace(":", " ").split()
                    # buscar el último número
                    for tok in reversed(tokens):
                        if tok.lstrip("-").isdigit():
                            num = int(tok)
                            coords.append(num)
                            break
                # timeout por duración
                if time.time() - start > duration:
                    break
        except Exception as e:
            print("Recorder error:", e)
        finally:
            try:
                p.kill()
            except:
                pass

        # intentar agrupar pares x,y
        pairs = []
        for i in range(0, len(coords)-1, 2):
            x = coords[i]; y = coords[i+1]
            pairs.append((x,y))
        # crear nodos Tap con esas coords
        for (x,y) in pairs:
            self.add_block("tap", f"Tap {x},{y}", x, y)
        messagebox.showinfo("Recorder", f"Recorder finalizado. {len(pairs)} eventos creados (aprox).")

    def record_actions(self):
        devices = list_devices()
        if not devices:
            messagebox.showwarning("No devices", "Conecta al menos un dispositivo.")
            return
        if len(devices) == 1:
            serial = devices[0]
        else:
            serial = simpledialog.askstring("Device", f"Dispositivo (lista: {devices}):")
            if serial not in devices:
                messagebox.showwarning("Device", "Selecciona un dispositivo válido.")
                return
        dur = simpledialog.askinteger("Recorder", "Duración grabación (segundos):", initialvalue=4, minvalue=1, maxvalue=30)
        if not dur: return
        threading.Thread(target=lambda: self.start_recorder_for_device(serial, duration=dur), daemon=True).start()