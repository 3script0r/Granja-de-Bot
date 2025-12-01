# visual_editor.py
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, scrolledtext
import json
import threading
import time
import subprocess
from adb_utils import list_devices, run_adb_cmd_raw
from script_executor import execute_script_for_device

class VisualFlowEditor(tk.Toplevel):
    BLOCK_W = 160
    BLOCK_H = 56
    PORT_SIZE = 12

    PALETTE = [
        {"type": "start", "label": "Start", "color": "#22c55e"},
        {"type": "stop", "label": "Stop", "color": "#ef4444"},
        {"type": "start_app", "label": "Abrir App", "color": "#3b82f6"},
        {"type": "open_link", "label": "Abrir Link", "color": "#3b82f6"},
        {"type": "tap", "label": "Tap (coords)", "color": "#8b5cf6"},
        {"type": "text", "label": "Escribir texto", "color": "#8b5cf6"},
        {"type": "swipe", "label": "Swipe", "color": "#8b5cf6"},
        {"type": "keyevent", "label": "Key Event", "color": "#8b5cf6"},
        {"type": "broadcast", "label": "Broadcast", "color": "#8b5cf6"},
        {"type": "shell", "label": "Shell Command", "color": "#8b5cf6"},
        {"type": "sleep", "label": "Esperar", "color": "#f97316"},
        {"type": "set_var", "label": "Variable =", "color": "#06b6d4"},
        {"type": "math_operation", "label": "Math Operation", "color": "#06b6d4"},
        {"type": "if", "label": "If Condition", "color": "#d946ef"},
        {"type": "else", "label": "Else", "color": "#d946ef"},
        {"type": "endif", "label": "End If", "color": "#d946ef"},
        {"type": "while", "label": "While Loop", "color": "#d946ef"},
        {"type": "endwhile", "label": "End While", "color": "#d946ef"},
        {"type": "uia_click", "label": "UIA Click", "color": "#ec4899"},
        {"type": "uia_text", "label": "UIA Escribir", "color": "#ec4899"},
        {"type": "uia_exists", "label": "UIA Exists", "color": "#ec4899"},
        {"type": "uia_scroll", "label": "UIA Scroll", "color": "#ec4899"},
    ]
    
    def __init__(self, master, inject_target_textwidget=None):
        super().__init__(master)
        self.title("Visual Script Builder — bloques y líneas")
        self.geometry("1400x800")
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

        # zoom
        self.zoom_level = 1.0

        self.create_widgets()
        
        # nodos base
        self.add_block("start", "Start", 120, 120)
        self.add_block("stop", "Stop", 900, 120)

    def create_widgets(self):
        # Main paned window for better layout
        main_paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel - Palette and controls
        left_panel = tk.Frame(main_paned, width=280)
        main_paned.add(left_panel, minsize=250, width=280)

        # Right panel - Canvas and toolbar
        right_panel = tk.Frame(main_paned)
        main_paned.add(right_panel, minsize=600)

        # Palette section
        palette_frame = tk.LabelFrame(left_panel, text="Paleta de acciones", padx=5, pady=5)
        palette_frame.pack(fill=tk.X, padx=5, pady=5)

        # Categorize palette items
        categories = {
            "Control": ["start", "stop"],
            "ADB Actions": ["start_app", "open_link", "tap", "text", "swipe", "keyevent", "broadcast", "shell"],
            "Flow Control": ["sleep", "set_var", "math_operation", "if", "else", "endif", "while", "endwhile"],
            "UIA Actions": ["uia_click", "uia_text", "uia_exists", "uia_scroll"]
        }

        for category, items in categories.items():
            cat_frame = tk.Frame(palette_frame)
            cat_frame.pack(fill=tk.X, pady=2)
            tk.Label(cat_frame, text=category, font=("Arial", 9, "bold")).pack(anchor=tk.W)
            
            for item_type in items:
                item = next((i for i in self.PALETTE if i["type"] == item_type), None)
                if item:
                    btn = tk.Button(cat_frame, text=item["label"], bg=item["color"], fg="white", 
                                  relief=tk.RAISED, padx=5, pady=2, width=20, anchor=tk.W)
                    btn.pack(fill=tk.X, pady=1)
                    btn.bind("<Button-1>", lambda e, it=item: self.add_block(it["type"], it["label"], 200, 200))
                    btn.bind("<Button-3>", lambda e, it=item: self.start_palette_drag(it, e))

        tk.Label(left_panel, text="(Click para agregar • Click-derecho para arrastrar)", 
                font=("Arial", 8), fg="gray").pack(pady=(0, 10))

        # Block operations section
        operations_frame = tk.LabelFrame(left_panel, text="Operaciones de bloques", padx=5, pady=5)
        operations_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(operations_frame, text="✏️ Editar parámetros", command=self.edit_selected_block, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(operations_frame, text="🗑️ Eliminar bloque", command=self.delete_selected_block, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(operations_frame, text="📋 Duplicar bloque", command=self.duplicate_selected_block, 
                 width=20).pack(fill=tk.X, pady=2)

        # Connections section
        connections_frame = tk.LabelFrame(left_panel, text="Conexiones", padx=5, pady=5)
        connections_frame.pack(fill=tk.X, padx=5, pady=5)

        self.connect_btn = tk.Button(connections_frame, text="🔗 Modo Conexión", 
                                    command=self.toggle_connect_mode, width=20)
        self.connect_btn.pack(fill=tk.X, pady=2)
        tk.Button(connections_frame, text="❌ Borrar conexión", command=self.delete_selected_edge, 
                 width=20).pack(fill=tk.X, pady=2)

        # Export section
        export_frame = tk.LabelFrame(left_panel, text="Exportar/Importar", padx=5, pady=5)
        export_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(export_frame, text="💾 Exportar a JSON", command=self.export_to_json, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(export_frame, text="📂 Guardar JSON…", command=self.save_json_file, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(export_frame, text="📂 Cargar JSON…", command=self.load_json_file, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(export_frame, text="▶ Ejecutar flujo", command=self.execute_from_editor, 
                 width=20).pack(fill=tk.X, pady=2)
        tk.Button(export_frame, text="⏺️ Grabar acciones", command=self.record_actions, 
                 width=20).pack(fill=tk.X, pady=2)

        # Variables monitor
        variables_frame = tk.LabelFrame(left_panel, text="Monitor de Variables", padx=5, pady=5)
        variables_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.vars_text = scrolledtext.ScrolledText(variables_frame, height=8, width=30)
        self.vars_text.pack(fill=tk.BOTH, expand=True)
        self.vars_text.config(state=tk.DISABLED)

        # Right panel - Canvas and toolbar
        # Toolbar
        toolbar = tk.Frame(right_panel, height=30, bg="#f0f0f0")
        toolbar.pack(fill=tk.X, pady=(0, 5))

        tk.Button(toolbar, text="🔍+", command=self.zoom_in).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="🔍-", command=self.zoom_out).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="🗑️ Limpiar Todo", command=self.clear_canvas).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="🎯 Alinear", command=self.align_blocks).pack(side=tk.LEFT, padx=2)
        
        tk.Label(toolbar, text="Lienzo: Arrastra bloques • Doble clic para editar • Rueda ratón para zoom", 
                bg="#f0f0f0").pack(side=tk.LEFT, padx=10)

        # Canvas with scrollbars
        canvas_frame = tk.Frame(right_panel)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas
        self.canvas = tk.Canvas(canvas_frame, bg="#1e293b", scrollregion=(0, 0, 3000, 3000))
        
        # Add scrollbars
        v_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Grid layout for canvas and scrollbars
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        # eventos
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)  # For Linux
        self.canvas.bind("<Button-5>", self.on_mousewheel)  # For Linux

    def add_block(self, item_type, label, x, y):
        nid = f"n{self.next_id}"
        self.next_id += 1
        
        # Get color from palette
        color = next((item["color"] for item in self.PALETTE if item["type"] == item_type), "#3b82f6")
        
        # Apply zoom
        x, y = x / self.zoom_level, y / self.zoom_level
        width, height = self.BLOCK_W * self.zoom_level, self.BLOCK_H * self.zoom_level
        
        rect = self.canvas.create_rectangle(x, y, x + width, y + height,
                                          fill=color, outline="#ffffff", width=2, 
                                          tags=("block", nid), activefill=self.lighten_color(color))
        
        text = self.canvas.create_text(x + width/2, y + height/2, text=label, 
                                     fill="white", tags=("block", nid), font=("Arial", int(10 * self.zoom_level)))
        
        # Only add output port if not an end block
        out_port = None
        if item_type not in ["stop", "endif", "endwhile", "else"]:
            out_port = self.canvas.create_oval(x + width - self.PORT_SIZE * self.zoom_level, 
                                             y + height/2 - (self.PORT_SIZE/2) * self.zoom_level,
                                             x + width, 
                                             y + height/2 + (self.PORT_SIZE/2) * self.zoom_level,
                                             fill="#38bdf8", outline="", 
                                             tags=("port_out", nid))
        
        # Only add input port if not a start block
        in_port = None
        if item_type not in ["start"]:
            in_port = self.canvas.create_oval(x, 
                                            y + height/2 - (self.PORT_SIZE/2) * self.zoom_level,
                                            x + self.PORT_SIZE * self.zoom_level, 
                                            y + height/2 + (self.PORT_SIZE/2) * self.zoom_level,
                                            fill="#22c55e", outline="", 
                                            tags=("port_in", nid))
        
        self.nodes[nid] = {
            "type": item_type, 
            "label": label, 
            "x": x, 
            "y": y, 
            "params": {}, 
            "canvas_ids": (rect, text), 
            "ports": (out_port, in_port),
            "color": color
        }
        
        return nid

    def lighten_color(self, color, amount=0.2):
        """Lighten a color by amount (0-1)"""
        try:
            import matplotlib.colors as mc
            import colorsys
            c = mc.cnames[color] if color in mc.cnames else color
            c = colorsys.rgb_to_hls(*mc.to_rgb(c))
            return mc.to_hex((
                c[0], 
                min(1, c[1] + amount), 
                min(1, c[2] + amount)
            ))
        except:
            return color

    def clear_selection(self):
        """Quita resaltado de nodo o arista seleccionada."""
        if self.selected_node:
            n = self.nodes.get(self.selected_node)
            if n:
                try:
                    rect = n["canvas_ids"][0]
                    self.canvas.itemconfig(rect, outline="#ffffff", width=2)
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
        self.temp_preview = self.canvas.create_rectangle(
            x, y, x + self.BLOCK_W * self.zoom_level, y + self.BLOCK_H * self.zoom_level,
            outline="#ffffff", dash=(4,2), fill=item["color"], alpha=0.7
        )
        self.canvas.update()

    def palette_drag_motion(self, event):
        if self.dragging_palette_item and self.temp_preview:
            x = self.winfo_pointerx() - self.canvas.winfo_rootx()
            y = self.winfo_pointery() - self.canvas.winfo_rooty()
            self.canvas.coords(
                self.temp_preview, 
                x, y, 
                x + self.BLOCK_W * self.zoom_level, 
                y + self.BLOCK_H * self.zoom_level
            )

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
            if n["x"] <= x <= n["x"] + self.BLOCK_W * self.zoom_level and n["y"] <= y <= n["y"] + self.BLOCK_H * self.zoom_level:
                return nid
        return None

    def redraw_node(self, nid):
        n = self.nodes[nid]
        x, y = n["x"], n["y"]
        width, height = self.BLOCK_W * self.zoom_level, self.BLOCK_H * self.zoom_level
        rect, text = n["canvas_ids"]
        
        self.canvas.coords(rect, x, y, x + width, y + height)
        self.canvas.coords(text, x + width/2, y + height/2)
        
        # Update ports
        out_port, in_port = n.get("ports", (None, None))
        if out_port:
            self.canvas.coords(
                out_port, 
                x + width - self.PORT_SIZE * self.zoom_level, 
                y + height/2 - (self.PORT_SIZE/2) * self.zoom_level,
                x + width, 
                y + height/2 + (self.PORT_SIZE/2) * self.zoom_level
            )
        if in_port:
            self.canvas.coords(
                in_port, 
                x, 
                y + height/2 - (self.PORT_SIZE/2) * self.zoom_level,
                x + self.PORT_SIZE * self.zoom_level, 
                y + height/2 + (self.PORT_SIZE/2) * self.zoom_level
            )
        
        # Update text font size
        self.canvas.itemconfig(text, font=("Arial", int(10 * self.zoom_level)))
        
        # update lines
        for (a, b, lid) in list(self.edges):
            if a == nid or b == nid:
                ax, ay = self.anchor_out(a)
                bx, by = self.anchor_in(b)
                try:
                    self.canvas.coords(lid, ax, ay, bx, by)
                except Exception:
                    pass

    def anchor_out(self, nid):
        n = self.nodes[nid]
        width = self.BLOCK_W * self.zoom_level
        return n["x"] + width, n["y"] + (self.BLOCK_H * self.zoom_level) / 2

    def anchor_in(self, nid):
        n = self.nodes[nid]
        return n["x"], n["y"] + (self.BLOCK_H * self.zoom_level) / 2

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
                    line = self.canvas.create_line(ax, ay, bx, by, fill="#94a3b8", 
                                                 width=2, arrow=tk.LAST, tags=("edge",),
                                                 arrowshape=(8, 10, 5))
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

    def on_mousewheel(self, event):
        # Zoom with mouse wheel
        if event.delta > 0 or event.num == 4:  # Scroll up or button 4 (Linux)
            self.zoom_in()
        elif event.delta < 0 or event.num == 5:  # Scroll down or button 5 (Linux)
            self.zoom_out()

    def zoom_in(self):
        if self.zoom_level < 2.0:
            self.zoom_level *= 1.1
            self.redraw_all()

    def zoom_out(self):
        if self.zoom_level > 0.5:
            self.zoom_level /= 1.1
            self.redraw_all()

    def redraw_all(self):
        for nid in self.nodes:
            self.redraw_node(nid)

    def toggle_connect_mode(self):
        self.connect_mode = not self.connect_mode
        self.connect_source_id = None
        self.connect_btn.config(
            relief=tk.SUNKEN if self.connect_mode else tk.RAISED,
            bg="#f59e0b" if self.connect_mode else "#f0f0f0"
        )

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
            if url is not None:
                n["params"]["url"] = url
                self.update_node_label(nid, f"Abrir Link\n{url[:20] + '...' if len(url) > 20 else url}")

        elif t == "start_app":
            pkg = simpledialog.askstring("Abrir App", "Package (ej: com.facebook.katana):", initialvalue=n["params"].get("package",""))
            if pkg: 
                n["params"]["package"] = pkg
                self.update_node_label(nid, f"Abrir App\n{pkg}")

        elif t == "tap":
            val = simpledialog.askstring("Tap", "x,y:", initialvalue=f"{n['params'].get('x','')},{n['params'].get('y','')}")
            if val and "," in val:
                try:
                    x,y = [int(v.strip()) for v in val.split(",")]
                    n["params"]["x"]=x
                    n["params"]["y"]=y
                    self.update_node_label(nid, f"Tap\n{x},{y}")
                except:
                    messagebox.showerror("Error","Coordenadas inválidas")

        elif t == "text":
            txt = simpledialog.askstring("Texto", "Texto a escribir:", initialvalue=n["params"].get("text",""))
            if txt is not None: 
                n["params"]["text"]=txt
                self.update_node_label(nid, f"Escribir\n{txt[:15] + '...' if len(txt) > 15 else txt}")

        elif t == "swipe":
            val = simpledialog.askstring("Swipe", "x1,y1,x2,y2,duration(ms):",
                                         initialvalue=f"{n['params'].get('x1','')},{n['params'].get('y1','')},{n['params'].get('x2','')},{n['params'].get('y2','')},{n['params'].get('duration',300)}")
            try:
                x1,y1,x2,y2,d = [int(v) for v in val.split(",")]
                n["params"].update({"x1":x1,"y1":y1,"x2":x2,"y2":y2,"duration":d})
                self.update_node_label(nid, f"Swipe\n({x1},{y1})→({x2},{y2})")
            except Exception:
                messagebox.showerror("Error","Parametros swipe invalidos")

        elif t == "sleep":
            s = simpledialog.askinteger("Esperar", "Segundos:", initialvalue=n["params"].get("seconds",1), minvalue=0)
            if s is not None: 
                n["params"]["seconds"]=int(s)
                self.update_node_label(nid, f"Esperar\n{s}s")

        elif t == "set_var":
            name = simpledialog.askstring("Variable", "Nombre de variable:", initialvalue=n["params"].get("name",""))
            val = simpledialog.askstring("Variable", "Valor:", initialvalue=n["params"].get("value",""))
            if name is not None:
                n["params"]["name"]=name
                n["params"]["value"]=val
                self.update_node_label(nid, f"Variable\n{name} = {val}")

        elif t == "math_operation":
            var_name = simpledialog.askstring("Math Operation", "Nombre de variable:", initialvalue=n["params"].get("var_name",""))
            operation = simpledialog.askstring("Math Operation", "Operación (add, subtract, multiply, divide, increment, decrement):", 
                                             initialvalue=n["params"].get("operation",""))
            value = simpledialog.askstring("Math Operation", "Valor (para increment/decrement puede estar vacío):", 
                                         initialvalue=n["params"].get("value",""))
            
            if var_name and operation:
                n["params"]["var_name"] = var_name
                n["params"]["operation"] = operation
                if value:
                    n["params"]["value"] = value
                self.update_node_label(nid, f"Math\n{var_name} {operation} {value if value else ''}")

        elif t == "if":
            condition = simpledialog.askstring("If Condition", "Condición (ej: ${counter} < 5):", 
                                             initialvalue=n["params"].get("condition",""))
            if condition is not None:
                n["params"]["condition"] = condition
                self.update_node_label(nid, f"If\n{condition}")

        elif t == "while":
            condition = simpledialog.askstring("While Loop", "Condición (ej: ${counter} < 5):", 
                                             initialvalue=n["params"].get("condition",""))
            max_iter = simpledialog.askinteger("While Loop", "Máximo de iteraciones:", 
                                             initialvalue=n["params"].get("max_iterations",100), minvalue=1)
            if condition is not None:
                n["params"]["condition"] = condition
                n["params"]["max_iterations"] = max_iter
                self.update_node_label(nid, f"While\n{condition}")

        elif t == "uia_click":
            val = simpledialog.askstring("UIA Click", "resourceId=... , text=...  (o x,y):", initialvalue=", ".join(f"{k}={v}" for k,v in n["params"].items()))
            if val:
                if "," in val and "=" not in val:
                    try:
                        x,y = [int(v.strip()) for v in val.split(",")]
                        n["params"]["x"]=x
                        n["params"]["y"]=y
                        self.update_node_label(nid, f"UIA Click\n{x},{y}")
                    except:
                        messagebox.showerror("Error","Coords invalidas")
                else:
                    for token in val.split(","):
                        if "=" in token:
                            k,v = token.split("=",1)
                            n["params"][k.strip()] = v.strip()
                    # Update label with first parameter
                    first_param = next(iter(n["params"].values()), "")
                    self.update_node_label(nid, f"UIA Click\n{first_param}")

        elif t == "uia_text":
            txt = simpledialog.askstring("UIA Escribir", "resourceId=... (opcional) ; text:", initialvalue=n["params"].get("text",""))
            if txt is not None:
                if "resourceId=" in txt or "text=" in txt:
                    parts = [p for p in txt.split(",") if "=" in p]
                    for p in parts:
                        k,v = p.split("=",1)
                        n["params"][k.strip()] = v.strip()
                    # Update label with text value
                    text_val = n["params"].get("text", "")
                    self.update_node_label(nid, f"UIA Text\n{text_val[:15] + '...' if len(text_val) > 15 else text_val}")
                else:
                    n["params"]["text"] = txt
                    self.update_node_label(nid, f"UIA Text\n{txt[:15] + '...' if len(txt) > 15 else txt}")

        elif t == "uia_exists":
            target = simpledialog.askstring("UIA Exists", "text=... or resourceId=...", 
                                          initialvalue=n["params"].get("text", n["params"].get("resourceId","")))
            result_var = simpledialog.askstring("UIA Exists", "Variable para resultado (opcional):", 
                                              initialvalue=n["params"].get("result_var",""))
            if target:
                if "=" in target:
                    k,v = target.split("=",1)
                    n["params"][k.strip()] = v.strip()
                else:
                    n["params"]["text"] = target
                if result_var:
                    n["params"]["result_var"] = result_var
                # Update label
                first_param = next(iter(n["params"].values()), "")
                self.update_node_label(nid, f"UIA Exists\n{first_param}")

        elif t == "shell":
            cmd = simpledialog.askstring("Shell Command", "Comando shell:", initialvalue=n["params"].get("command",""))
            if cmd is not None:
                n["params"]["command"] = cmd
                self.update_node_label(nid, f"Shell\n{cmd[:20] + '...' if len(cmd) > 20 else cmd}")

        elif t == "keyevent":
            key = simpledialog.askstring("Key Event", "Código de tecla:", initialvalue=n["params"].get("key",""))
            if key is not None:
                n["params"]["key"] = key
                self.update_node_label(nid, f"Key Event\n{key}")

        elif t == "broadcast":
            intent = simpledialog.askstring("Broadcast", "Intent:", initialvalue=n["params"].get("intent",""))
            if intent is not None:
                n["params"]["intent"] = intent
                self.update_node_label(nid, f"Broadcast\n{intent}")

    def update_node_label(self, nid, new_label):
        n = self.nodes[nid]
        n["label"] = new_label
        text_id = n["canvas_ids"][1]
        self.canvas.itemconfig(text_id, text=new_label)

    def duplicate_selected_block(self):
        nid = self.selected_node
        if not nid:
            messagebox.showinfo("Info", "Selecciona un bloque para duplicarlo.")
            return
        
        n = self.nodes[nid]
        new_nid = self.add_block(n["type"], n["label"], n["x"] + 50, n["y"] + 50)
        self.nodes[new_nid]["params"] = n["params"].copy()
        self.select_node(new_nid)

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

    def clear_canvas(self):
        if messagebox.askyesno("Confirmar", "¿Estás seguro de que quieres limpiar todo el lienzo?"):
            # Delete all nodes and edges
            for nid in list(self.nodes.keys()):
                for item in self.canvas.find_withtag(nid):
                    self.canvas.delete(item)
                self.nodes.pop(nid, None)
            
            for (a, b, lid) in list(self.edges):
                try:
                    self.canvas.delete(lid)
                except:
                    pass
                self.edges.remove((a, b, lid))
            
            # Add start and stop blocks again
            self.add_block("start", "Start", 120, 120)
            self.add_block("stop", "Stop", 900, 120)
            
            self.selected_node = None
            self.selected_edge = None

    def align_blocks(self):
        # Simple alignment - arrange blocks in a grid
        if not self.nodes:
            return
            
        start_x, start_y = 100, 100
        grid_width = 4
        spacing_x, spacing_y = 200, 100
        
        nodes_list = list(self.nodes.items())
        for i, (nid, node) in enumerate(nodes_list):
            row = i // grid_width
            col = i % grid_width
            node["x"] = start_x + col * spacing_x
            node["y"] = start_y + row * spacing_y
            self.redraw_node(nid)

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

    def load_json_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Files","*.json")])
        if not path:
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                script = json.load(f)
                
            # Clear current canvas
            self.clear_canvas()
            
            # Load steps from JSON
            if isinstance(script, dict) and "steps" in script:
                steps = script["steps"]
            elif isinstance(script, list):
                steps = script
            else:
                messagebox.showerror("Error", "Formato de JSON inválido")
                return
                
            # Position variables
            x, y = 200, 150
            y_increment = 100
            
            # Create blocks for each step
            for step in steps:
                action = step.get("action")
                label = action
                
                # Create appropriate label
                if action == "set_var":
                    label = f"Variable\n{step.get('name', '')} = {step.get('value', '')}"
                elif action == "math_operation":
                    label = f"Math\n{step.get('var_name', '')} {step.get('operation', '')} {step.get('value', '')}"
                elif action == "if":
                    label = f"If\n{step.get('condition', '')}"
                elif action == "while":
                    label = f"While\n{step.get('condition', '')}"
                elif action == "tap":
                    label = f"Tap\n{step.get('x', '')},{step.get('y', '')}"
                elif action == "text":
                    text = step.get('text', '')
                    label = f"Escribir\n{text[:15] + '...' if len(text) > 15 else text}"
                elif action == "start_app":
                    label = f"Abrir App\n{step.get('package', '')}"
                elif action == "open_link":
                    url = step.get('url', '')
                    label = f"Abrir Link\n{url[:20] + '...' if len(url) > 20 else url}"
                
                nid = self.add_block(action, label, x, y)
                self.nodes[nid]["params"] = {k: v for k, v in step.items() if k != "action"}
                y += y_increment
                
            messagebox.showinfo("Cargado", f"Flujo cargado desde:\n{path}")
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el archivo: {e}")

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
                self.inject_target.see(tk.END)
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

# Ejecutar directamente para pruebas
if __name__ == "__main__":
    root = tk.Tk()
    editor = VisualFlowEditor(root)
    root.mainloop()