# script_executor_enhanced.py
import time
import shlex
from adb_utils import run_adb_command, run_adb_cmd_raw




# Intentar importar uiautomator2 (si no está, la app sigue funcionando con ADB)
try:
    import uiautomator2 as u2
except Exception:
    u2 = None

def execute_script_for_device(serial, script, log_callback=None, stop_event=None):
    """
    Ejecuta un script con mejor manejo de errores y capacidades extendidas.
    """
    # Normalizar steps
    if isinstance(script, dict) and "steps" in script:
        steps = script["steps"]
    elif isinstance(script, list):
        steps = script
    else:
        if log_callback:
            log_callback(f"[{serial}] Script inválido", "error")
        return False

    # Intentar conectar uiautomator2
    d = None
    if u2 is not None:
        try:
            d = u2.connect(serial)
            if log_callback:
                log_callback(f"[{serial}] UIAutomator2 conectado.", "info")
        except Exception as e:
            d = None
            if log_callback:
                log_callback(f"[{serial}] UIA connect falló: {e}. Usando ADB cuando sea posible.", "warning")

    vars_store = {}  # para variables simples
    execution_stats = {
        "total_steps": len(steps),
        "executed_steps": 0,
        "failed_steps": 0,
        "start_time": time.time()
    }

    # Pila para bucles while
    loop_stack = []
    current_step = 0

    while current_step < len(steps):
        if stop_event and stop_event.is_set():
            if log_callback: 
                log_callback(f"[{serial}] Ejecución interrumpida por stop_event.", "warning")
            break

        step = steps[current_step]
        action = step.get("action")
        
        if log_callback:
            log_callback(f"[{serial}] Step {current_step + 1}: {action} -> {step}", "info")

        try:
            # Manejar break y continue primero
            if action == "break":
                if loop_stack:
                    # Saltar al final del bucle
                    loop_info = loop_stack.pop()
                    current_step = loop_info["end_step"]
                    continue
                else:
                    log_callback(f"[{serial}] Break fuera de bucle", "warning")
            
            elif action == "continue":
                if loop_stack:
                    # Volver al inicio del bucle
                    loop_info = loop_stack[-1]
                    current_step = loop_info["start_step"]
                    continue
                else:
                    log_callback(f"[{serial}] Continue fuera de bucle", "warning")
            
            # Ejecutar acciones normales
            elif action == "set_var":
                name = step.get("name")
                value = step.get("value")
                if name:
                    # Intentar evaluar expresiones matemáticas
                    try:
                        if isinstance(value, str) and any(op in value for op in ['+', '-', '*', '/']):
                            # Reemplazar variables existentes en la expresión
                            for var_name, var_value in vars_store.items():
                                if isinstance(var_value, (int, float)) and var_name in value:
                                    value = value.replace(var_name, str(var_value))
                            # Evaluar la expresión
                            value = eval(value)
                    except:
                        pass  # Si falla la evaluación, mantener el valor como string
                    
                    vars_store[name] = value
                    if log_callback: 
                        log_callback(f"[{serial}] variable {name} = {value}", "info")
            
            elif action == "increment_var":
                name = step.get("name")
                increment = step.get("increment", 1)
                if name and name in vars_store and isinstance(vars_store[name], (int, float)):
                    vars_store[name] += increment
                    if log_callback: 
                        log_callback(f"[{serial}] variable {name} += {increment} = {vars_store[name]}", "info")
            
            elif action == "decrement_var":
                name = step.get("name")
                decrement = step.get("decrement", 1)
                if name and name in vars_store and isinstance(vars_store[name], (int, float)):
                    vars_store[name] -= decrement
                    if log_callback: 
                        log_callback(f"[{serial}] variable {name} -= {decrement} = {vars_store[name]}", "info")
            
            elif action == "math_operation":
                name = step.get("name")
                operation = step.get("operation", "")
                if name and name in vars_store and isinstance(vars_store[name], (int, float)) and operation:
                    try:
                        # Ejecutar operación matemática
                        current_value = vars_store[name]
                        result = eval(f"{current_value} {operation}")
                        vars_store[name] = result
                        if log_callback: 
                            log_callback(f"[{serial}] variable {name} {operation} = {result}", "info")
                    except Exception as e:
                        if log_callback: 
                            log_callback(f"[{serial}] Error en operación matemática: {e}", "error")
            
            elif action == "if":
                cond_type = step.get("cond_type", "var_equals")
                skip = step.get("skip", 1)
                condition_met = False
                
                if cond_type == "var_equals":
                    name = step.get("name")
                    value = step.get("value")
                    if name in vars_store:
                        # Intentar comparar numéricamente si es posible
                        try:
                            var_value = float(vars_store[name]) if isinstance(vars_store[name], (int, float, str)) and str(vars_store[name]).replace('.', '', 1).isdigit() else vars_store[name]
                            cmp_value = float(value) if str(value).replace('.', '', 1).isdigit() else value
                            condition_met = (var_value == cmp_value)
                        except:
                            condition_met = (str(vars_store[name]) == str(value))
                
                elif cond_type == "var_greater":
                    name = step.get("name")
                    value = step.get("value")
                    if name in vars_store and isinstance(vars_store[name], (int, float)):
                        try:
                            cmp_value = float(value)
                            condition_met = (vars_store[name] > cmp_value)
                        except:
                            pass
                
                elif cond_type == "var_less":
                    name = step.get("name")
                    value = step.get("value")
                    if name in vars_store and isinstance(vars_store[name], (int, float)):
                        try:
                            cmp_value = float(value)
                            condition_met = (vars_store[name] < cmp_value)
                        except:
                            pass
                
                elif cond_type == "var_exists":
                    name = step.get("name")
                    condition_met = (name in vars_store)
                
                elif cond_type == "uia_exists":
                    if d is not None:
                        if "resourceId" in step:
                            condition_met = d(resourceId=step["resourceId"]).exists
                        elif "text" in step:
                            condition_met = d(text=step["text"]).exists
                
                if not condition_met:
                    # Saltar los siguientes 'skip' pasos
                    current_step += skip
                    continue
            
            elif action == "while":
                cond_type = step.get("cond_type", "var_equals")
                max_iterations = step.get("max_iterations", 0)
                condition_met = False
                iteration_count = 0
                
                # Verificar condición inicial
                if cond_type == "var_equals":
                    name = step.get("name")
                    value = step.get("value")
                    if name in vars_store:
                        try:
                            var_value = float(vars_store[name]) if isinstance(vars_store[name], (int, float, str)) and str(vars_store[name]).replace('.', '', 1).isdigit() else vars_store[name]
                            cmp_value = float(value) if str(value).replace('.', '', 1).isdigit() else value
                            condition_met = (var_value == cmp_value)
                        except:
                            condition_met = (str(vars_store[name]) == str(value))
                
                # ... (otros tipos de condiciones similares al if)
                
                if condition_met:
                    # Guardar información del bucle en la pila
                    loop_info = {
                        "start_step": current_step,
                        "end_step": current_step + step.get("skip", 1),
                        "max_iterations": max_iterations,
                        "iteration_count": 0
                    }
                    loop_stack.append(loop_info)
                else:
                    # Saltar el cuerpo del bucle
                    current_step += step.get("skip", 1)
                    continue
            
            # ... (resto de acciones existentes: open_link, start_app, tap, text, etc.)
            
            # Incrementar contador de pasos ejecutados
            execution_stats["executed_steps"] += 1
            
            # Avanzar al siguiente paso
            current_step += 1
            
        except Exception as e:
            execution_stats["failed_steps"] += 1
            if log_callback:
                log_callback(f"[{serial}] ERROR en step {current_step + 1}: {e}", "error")
            
            # Opción para continuar o detener en error
            if step.get("stop_on_error", False):
                break
            
            current_step += 1

    execution_stats["end_time"] = time.time()
    execution_stats["duration"] = execution_stats["end_time"] - execution_stats["start_time"]
    
    if log_callback:
        success_rate = (execution_stats["executed_steps"] - execution_stats["failed_steps"]) / execution_stats["executed_steps"] * 100 if execution_stats["executed_steps"] > 0 else 0
        log_callback(
            f"[{serial}] Script finalizado. "
            f"Ejecutados: {execution_stats['executed_steps']}/{execution_stats['total_steps']} "
            f"({success_rate:.1f}% éxito) en {execution_stats['duration']:.1f}s",
            "info"
        )
    
    return execution_stats