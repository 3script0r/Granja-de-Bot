# script_executor.py (versión mejorada)
import time
import shlex
import re
from adb_utils import run_adb_command, run_adb_cmd_raw

# Intentar importar uiautomator2 (si no está, la app sigue funcionando con ADB)
try:
    import uiautomator2 as u2
except Exception:
    u2 = None

def execute_script_for_device(serial, script, log_cb=None, stop_event=None):
    """
    Ejecuta un script (dict con key 'steps' o lista de pasos) en un dispositivo.
    Soporte mejorado para:
      - Variables: asignación, operaciones matemáticas
      - Condicionales: if/else, comparaciones complejas
      - Bucles: while con condiciones
      - ADB actions: start_app, tap, text, keyevent, swipe, broadcast, sleep
      - UIA actions: uia_click, uia_text, uia_exists, uia_scroll
    stop_event: threading.Event para parar ejecución si es necesario
    """
    # Normalizar steps
    if isinstance(script, dict) and "steps" in script:
        steps = script["steps"]
    elif isinstance(script, list):
        steps = script
    else:
        if log_cb:
            log_cb(f"[{serial}] Script inválido")
        return

    # intento de conectar uiautomator2
    d = None
    if u2 is not None:
        try:
            d = u2.connect(serial)
            if log_cb:
                log_cb(f"[{serial}] UIAutomator2 conectado.")
        except Exception as e:
            d = None
            if log_cb:
                log_cb(f"[{serial}] UIA connect falló: {e}. Usando ADB cuando sea posible.")

    vars_store = {}  # para variables
    loop_stack = []  # para manejar bucles anidados
    step_idx = 0     # índice del paso actual
    
    # Función para evaluar expresiones con variables
    def eval_expression(expr):
        if isinstance(expr, (int, float, bool)):
            return expr
        if isinstance(expr, str):
            # Reemplazar variables en la expresión
            for var_name, var_value in vars_store.items():
                expr = expr.replace(f"${{{var_name}}}", str(var_value))
            
            # Intentar evaluar como expresión matemática
            try:
                # Verificar si es una expresión matemática válida
                if re.match(r'^[\d\s\+\-\*\/\(\)\.\%\<\>\=\!\&\\|]+$', expr):
                    # Reemplazar operadores lógicos
                    expr = expr.replace('==', '==').replace('!=', '!=').replace('<=', '<=').replace('>=', '>=')
                    expr = expr.replace(' and ', ' and ').replace(' or ', ' or ')
                    
                    # Evaluar expresión
                    return eval(expr, {"__builtins__": None}, {})
            except:
                pass
            
            # Si no es una expresión matemática, devolver el string
            return expr
        return expr

    # Función para evaluar condiciones
    def eval_condition(condition):
        if isinstance(condition, bool):
            return condition
        
        if isinstance(condition, str):
            # Reemplazar variables en la condición
            for var_name, var_value in vars_store.items():
                condition = condition.replace(f"${{{var_name}}}", str(var_value))
            
            # Intentar evaluar como expresión booleana
            try:
                # Reemplazar operadores lógicos
                condition = condition.replace(' and ', ' and ').replace(' or ', ' or ')
                condition = condition.replace('==', '==').replace('!=', '!=').replace('<=', '<=').replace('>=', '>=')
                
                # Evaluar condición
                return eval(condition, {"__builtins__": None}, {})
            except:
                # Si falla la evaluación, tratar como comparación de strings
                if "==" in condition:
                    parts = condition.split("==", 1)
                    return str(parts[0]).strip() == str(parts[1]).strip()
                elif "!=" in condition:
                    parts = condition.split("!=", 1)
                    return str(parts[0]).strip() != str(parts[1]).strip()
                elif " contains " in condition:
                    parts = condition.split(" contains ", 1)
                    return str(parts[1]).strip() in str(parts[0]).strip()
                else:
                    # Condición no reconocida, tratar como False
                    return False
        
        return False

    while step_idx < len(steps):
        if stop_event and stop_event.is_set():
            if log_cb: log_cb(f"[{serial}] Ejecución interrumpida por stop_event.")
            break

        step = steps[step_idx]
        action = step.get("action")
        if log_cb:
            log_cb(f"[{serial}] Step {step_idx+1}: {action} -> {step}")

        try:
            # Manejo de bucles
            if action == "while":
                condition = step.get("condition", "")
                loop_id = step.get("loop_id", f"loop_{step_idx}")
                
                # Evaluar condición
                condition_met = eval_condition(condition)
                
                if condition_met:
                    # Guardar posición para volver
                    if not any(loop["loop_id"] == loop_id for loop in loop_stack):
                        loop_stack.append({
                            "loop_id": loop_id,
                            "start_idx": step_idx,
                            "max_iterations": step.get("max_iterations", 100),
                            "iteration": 0
                        })
                    
                    # Avanzar al siguiente paso
                    step_idx += 1
                    continue
                else:
                    # Condición no cumplida, saltar al endwhile correspondiente
                    endwhile_idx = find_matching_endwhile(steps, step_idx)
                    if endwhile_idx != -1:
                        step_idx = endwhile_idx + 1
                    else:
                        step_idx += 1
                    continue
            
            elif action == "endwhile":
                # Volver al inicio del bucle
                current_loop = loop_stack[-1] if loop_stack else None
                if current_loop:
                    # Verificar máximo de iteraciones
                    current_loop["iteration"] += 1
                    if current_loop["iteration"] >= current_loop["max_iterations"]:
                        if log_cb: log_cb(f"[{serial}] Bucle excedió el máximo de iteraciones ({current_loop['max_iterations']})")
                        loop_stack.pop()
                        step_idx += 1
                        continue
                    
                    # Volver al inicio del bucle
                    step_idx = current_loop["start_idx"]
                else:
                    step_idx += 1
                continue
            
            # Condicionales mejorados
            elif action == "if":
                condition = step.get("condition", "")
                condition_met = eval_condition(condition)
                
                if not condition_met:
                    # Saltar al else o endif correspondiente
                    else_idx = find_matching_else(steps, step_idx)
                    endif_idx = find_matching_endif(steps, step_idx)
                    
                    if else_idx != -1:
                        step_idx = else_idx + 1
                    elif endif_idx != -1:
                        step_idx = endif_idx + 1
                    else:
                        step_idx += 1
                else:
                    step_idx += 1
                continue
            
            elif action == "else":
                # Saltar al endif correspondiente (solo se ejecuta si el if fue falso)
                endif_idx = find_matching_endif(steps, step_idx)
                if endif_idx != -1:
                    step_idx = endif_idx + 1
                else:
                    step_idx += 1
                continue
            
            elif action == "endif":
                # Simplemente continuar
                step_idx += 1
                continue
            
            # Asignación de variables mejorada
            elif action == "set_var":
                name = step.get("name")
                value = step.get("value")
                
                if name:
                    # Evaluar expresión si es necesario
                    evaluated_value = eval_expression(value)
                    vars_store[name] = evaluated_value
                    
                    if log_cb: 
                        log_cb(f"[{serial}] variable {name} = {evaluated_value} (tipo: {type(evaluated_value).__name__})")
                
                step_idx += 1
                continue
            
            # Operaciones matemáticas con variables
            elif action == "math_operation":
                var_name = step.get("var_name")
                operation = step.get("operation")
                value = step.get("value")
                
                if var_name and var_name in vars_store and operation:
                    current_value = vars_store[var_name]
                    value = eval_expression(value)
                    
                    try:
                        if operation == "add":
                            vars_store[var_name] = current_value + value
                        elif operation == "subtract":
                            vars_store[var_name] = current_value - value
                        elif operation == "multiply":
                            vars_store[var_name] = current_value * value
                        elif operation == "divide":
                            if value != 0:
                                vars_store[var_name] = current_value / value
                            else:
                                if log_cb: log_cb(f"[{serial}] Error: División por cero")
                        elif operation == "increment":
                            vars_store[var_name] = current_value + 1
                        elif operation == "decrement":
                            vars_store[var_name] = current_value - 1
                        
                        if log_cb: 
                            log_cb(f"[{serial}] {var_name} = {vars_store[var_name]} después de {operation}")
                    except Exception as e:
                        if log_cb: log_cb(f"[{serial}] Error en operación matemática: {e}")
                
                step_idx += 1
                continue
            
            # ADB actions (existentes, pero con soporte para variables)
            elif action == "open_link":
                url = step.get("url")
                if url:
                    url = str(eval_expression(url))
                    run_adb_command(serial, f"shell am start -a android.intent.action.VIEW -d \"{url}\"")
                    time.sleep(step.get("wait", 1))
                else:
                    if log_cb: log_cb(f"[{serial}] open_link sin URL")
           
            elif action == "shell":
                cmd = step.get("command", "")
                if cmd:
                    cmd = str(eval_expression(cmd))
                    # Ejecutar comando shell directamente
                    full_cmd = ["adb", "-s", serial, "shell"] + shlex.split(cmd)
                    out, err, rc = run_adb_cmd_raw(full_cmd)
                    if log_cb:
                        log_cb(f"[{serial}] Shell: {cmd}")
                        if out: log_cb(f"[{serial}] Output: {out}")
                        if err: log_cb(f"[{serial}] Error: {err}")
                time.sleep(step.get("wait", 0.5))   

            elif action == "start_app":
                pkg = step.get("package")
                if pkg:
                    pkg = str(eval_expression(pkg))
                    run_adb_command(serial, f"shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
                    time.sleep(step.get("wait", 1))
                else:
                    if log_cb: log_cb(f"[{serial}] start_app sin package")

            elif action == "tap":
                x = eval_expression(step.get("x"))
                y = eval_expression(step.get("y"))
                if x is None or y is None:
                    if log_cb: log_cb(f"[{serial}] tap sin coords")
                else:
                    run_adb_command(serial, f"shell input tap {int(x)} {int(y)}")
                time.sleep(step.get("wait", 0.5))

            elif action == "text":
                txt = step.get("text", "")
                txt = str(eval_expression(txt))
                safe = txt.replace(" ", "%s")
                run_adb_command(serial, f"shell input text {safe}")
                time.sleep(step.get("wait", 0.4))

            elif action == "keyevent":
                key = step.get("key")
                if key is not None:
                    key = eval_expression(key)
                    run_adb_command(serial, f"shell input keyevent {key}")
                time.sleep(step.get("wait", 0.2))

            elif action == "swipe":
                x1 = eval_expression(step.get("x1"))
                y1 = eval_expression(step.get("y1"))
                x2 = eval_expression(step.get("x2"))
                y2 = eval_expression(step.get("y2"))
                dur = eval_expression(step.get("duration", 300))
                
                if None in (x1, y1, x2, y2):
                    if log_cb: log_cb(f"[{serial}] swipe sin coords")
                else:
                    run_adb_command(serial, f"shell input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(dur)}")
                time.sleep(step.get("wait", 0.5))

            elif action == "broadcast":
                intent = step.get("intent")
                if intent:
                    intent = str(eval_expression(intent))
                    run_adb_command(serial, f"shell am broadcast -a {intent}")
                time.sleep(step.get("wait", 0.2))

            elif action == "sleep":
                secs = float(eval_expression(step.get("seconds", 1)))
                if log_cb: log_cb(f"[{serial}] durmiendo {secs}s")
                time.sleep(secs)

            # UIAutomator2 actions (más precisas)
            elif action == "uia_click":
                if d is None:
                    # fallback to adb tap if coords
                    x = eval_expression(step.get("x"))
                    y = eval_expression(step.get("y"))
                    if x is not None and y is not None:
                        run_adb_command(serial, f"shell input tap {int(x)} {int(y)}")
                        time.sleep(step.get("wait", 0.3))
                    else:
                        if log_cb: log_cb(f"[{serial}] uia_click solicitado pero UIA no disponible y sin coords")
                else:
                    if "resourceId" in step:
                        resourceId = str(eval_expression(step["resourceId"]))
                        d(resourceId=resourceId).click_exists(timeout=5)
                    elif "text" in step:
                        text = str(eval_expression(step["text"]))
                        d(text=text).click_exists(timeout=5)
                    elif "description" in step:
                        description = str(eval_expression(step["description"]))
                        d(description=description).click_exists(timeout=5)
                    elif "x" in step and "y" in step:
                        x = eval_expression(step["x"])
                        y = eval_expression(step["y"])
                        d.click(int(x), int(y))
                    time.sleep(step.get("wait", 0.4))

            elif action == "uia_text":
                if d is None:
                    txt = step.get("text", "")
                    txt = str(eval_expression(txt))
                    safe = txt.replace(" ", "%s")
                    run_adb_command(serial, f"shell input text {safe}")
                else:
                    text_val = str(eval_expression(step.get("text", "")))
                    if "resourceId" in step:
                        resourceId = str(eval_expression(step["resourceId"]))
                        elem = d(resourceId=resourceId)
                        if elem.exists:
                            try:
                                elem.set_text(text_val)
                            except Exception:
                                d.send_keys(text_val)
                        else:
                            d.send_keys(text_val)
                    else:
                        d.send_keys(text_val)
                time.sleep(step.get("wait", 0.4))

            elif action == "uia_exists":
                exists = False
                if d is not None:
                    if "resourceId" in step:
                        resourceId = str(eval_expression(step["resourceId"]))
                        exists = d(resourceId=resourceId).exists
                    elif "text" in step:
                        text = str(eval_expression(step["text"]))
                        exists = d(text=text).exists
                    elif "description" in step:
                        description = str(eval_expression(step["description"]))
                        exists = d(description=description).exists
                
                # Guardar resultado en variable si se especifica
                result_var = step.get("result_var")
                if result_var:
                    vars_store[result_var] = exists
                
                if log_cb:
                    log_cb(f"[{serial}] uia_exists -> {exists}")
                time.sleep(step.get("wait", 0.2))

            elif action == "uia_scroll":
                if d is not None:
                    if "text" in step:
                        text = str(eval_expression(step["text"]))
                        try:
                            d(scrollable=True).scroll.to(text=text)
                        except Exception:
                            run_adb_command(serial, f"shell input swipe 300 1200 300 400 400")
                time.sleep(step.get("wait", 0.4))

            else:
                if log_cb:
                    log_cb(f"[{serial}] Acción desconocida: {action}")
                
            step_idx += 1

        except Exception as e:
            if log_cb:
                log_cb(f"[{serial}] ERROR en step {step_idx+1}: {e}")
            step_idx += 1

    if log_cb:
        log_cb(f"[{serial}] Script finalizado.")

# Funciones auxiliares para encontrar bloques coincidentes
def find_matching_endwhile(steps, while_idx):
    """Encuentra el endwhile que corresponde a un while"""
    depth = 0
    for i in range(while_idx + 1, len(steps)):
        action = steps[i].get("action")
        if action == "while":
            depth += 1
        elif action == "endwhile":
            if depth == 0:
                return i
            depth -= 1
    return -1

def find_matching_else(steps, if_idx):
    """Encuentra el else que corresponde a un if"""
    depth = 0
    for i in range(if_idx + 1, len(steps)):
        action = steps[i].get("action")
        if action == "if":
            depth += 1
        elif action == "else" and depth == 0:
            return i
        elif action == "endif":
            if depth == 0:
                return -1
            depth -= 1
    return -1

def find_matching_endif(steps, start_idx):
    """Encuentra el endif que corresponde a un if o else"""
    depth = 0
    for i in range(start_idx + 1, len(steps)):
        action = steps[i].get("action")
        if action == "if":
            depth += 1
        elif action == "endif":
            if depth == 0:
                return i
            depth -= 1
    return -1