import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

ROOT = Path(__file__).resolve().parent.parent
FORMULAS_PATH = ROOT / "data" / "formulas_db.json"

_formulas_db = []
if FORMULAS_PATH.exists():
    try:
        with open(FORMULAS_PATH, encoding="utf-8") as f:
            _formulas_db = json.load(f).get("formulas", [])
    except Exception as e:
        print("Formula load error:", e)

def _try_recover_from_raw(parsed: Any) -> dict:
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", parsed, re.DOTALL | re.I)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        start = parsed.find("{")
        end = parsed.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(parsed[start:end+1])
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {"error": "cannot_recover", "raw": str(parsed)}

def format_answer(target: str, val: float) -> str:
    if val is None or math.isnan(val) or math.isinf(val):
        return "Unknown"
    
    target_l = str(target).lower()
    
    if target_l in ("c", "c1", "c2"):
        if val < 1e-9:
            return f"{val / 1e-12:.4g} pF"
        elif val < 1e-6:
            return f"{val / 1e-9:.4g} nF"
        elif val < 1e-3:
            return f"{val / 1e-6:.4g} \\u03bcF"
        else:
            return f"{val:.4g} F"
            
    if target_l in ("q", "q1", "q2", "q3", "q_new", "q0", "qo"):
        abs_val = abs(val)
        sign = "-" if val < 0 else ""
        if abs_val < 1e-9:
            return f"{sign}{abs_val / 1e-12:.4g} pC"
        elif abs_val < 1e-6:
            return f"{sign}{abs_val / 1e-9:.4g} nC"
        elif abs_val < 1e-3:
            return f"{sign}{abs_val / 1e-6:.4g} \\u03bcC"
        else:
            return f"{sign}{abs_val:.4g} C"
            
    if target_l in ("e", "w"):
        if val < 1e-9:
            return f"{val / 1e-12:.4g} pJ"
        elif val < 1e-6:
            return f"{val / 1e-9:.4g} nJ"
        elif val < 1e-3:
            return f"{val / 1e-6:.4g} \\u03bcJ"
        elif val < 1.0:
            return f"{val / 1e-3:.4g} mJ"
        else:
            return f"{val:.4g} J"
            
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    return f"{val:.4g}"

def solve_physics_payload(payload: dict) -> dict:
    if not isinstance(payload, dict) or "error" in payload:
        return {"success": False, "msg": payload.get("error", "Invalid payload")}
        
    task_type = payload.get("task_type")
    
    if task_type == "algebraic":
        return _solve_algebraic(payload)
    elif task_type == "vector_resultant":
        return _solve_vector(payload)
    elif task_type in ("coulomb_geometry", "coulomb_collinear"):
        return _solve_coulomb_layout(payload)
    elif task_type == "coulomb_bisector":
        return _solve_coulomb_bisector(payload)
    elif task_type == "coulomb_field":
        return _solve_coulomb_field(payload)
    elif task_type == "coulomb_pair":
        return _solve_coulomb_pair(payload)
    elif task_type == "coulomb_equilibrium":
        return _solve_coulomb_equilibrium(payload)
    elif task_type == "solve_angle":
        return _solve_angle(payload)
        
    return {"success": False, "msg": f"Unsupported task type: {task_type}"}

def _solve_algebraic(payload: dict) -> dict:
    target = payload.get("target")
    knowns = payload.get("knowns", {})
    
    inputs_dict = {}
    for k, v in knowns.items():
        if isinstance(v, dict) and "value" in v:
            inputs_dict[k] = v["value"]
            unit = str(v.get("unit", "")).lower()
            scale = {
                "uf": 1e-6, "μf": 1e-6, "µf": 1e-6, "nf": 1e-9, "pf": 1e-12, "f": 1.0,
                "v": 1.0, "kv": 1e3, "mv": 1e-3,
                "h": 1.0, "mh": 1e-3, "uh": 1e-6, "μh": 1e-6, "µh": 1e-6,
                "a": 1.0, "ma": 1e-3, "ua": 1e-6,
                "uc": 1e-6, "mc": 1e-3, "nc": 1e-9, "pc": 1e-12, "c": 1.0,
                "cm": 1e-2, "mm": 1e-3, "m": 1.0, "cm2": 1e-4, "mm2": 1e-6,
                "hz": 1.0, "khz": 1e3, "mhz": 1e6,
                "n": 1.0, "mn": 1e-3,
            }
            if unit in scale:
                inputs_dict[k] *= scale[unit]
        else:
            inputs_dict[k] = float(v)

    if "_dielectric_mode" in inputs_dict:
        mode_val = inputs_dict.pop("_dielectric_mode")
        if mode_val == "connected" or mode_val == 1:
            inputs_dict["epsilon"] = knowns.get("epsilon", {}).get("value", 1.0)
            
    matched_formula = None
    for f in _formulas_db:
        if f["target"] == target:
            if all(inp in inputs_dict for inp in f["inputs"]):
                matched_formula = f
                break
                
    if not matched_formula:
        return {"success": False, "msg": f"No formula found for target {target} with inputs {list(inputs_dict.keys())}"}
        
    equation = matched_formula["equation"]
    try:
        scope = {
            "math": math,
            "abs": abs,
            "min": min,
            "max": max,
            "pow": pow,
            "round": round
        }
        scope.update(inputs_dict)
        ans = eval(equation, {"__builtins__": {}}, scope)
        display = format_answer(target, ans)
        
        solution = f"Sử dụng công thức {matched_formula['id']}: {target} = {equation}\n"
        solution += "Các giá trị đã biết:\n"
        for k, v in inputs_dict.items():
            solution += f"- {k} = {v}\n"
        solution += f"Kết quả tính toán: {target} = {display}"
        
        return {
            "success": True,
            "answer": ans,
            "answer_display": display,
            "formula_id": matched_formula["id"],
            "equation": equation,
            "solution": solution,
        }
    except Exception as e:
        return {"success": False, "msg": f"Formula evaluation error: {e}"}

def _solve_vector(payload: dict) -> dict:
    mode = payload.get("mode")
    
    def extract_val(v_dict) -> float:
        if isinstance(v_dict, dict):
            return float(v_dict["value"])
        return float(v_dict)
        
    if "F1" not in payload or "F2" not in payload:
        return {"success": False, "msg": "Missing F1 or F2 in vector payload"}
    f1 = extract_val(payload["F1"])
    f2 = extract_val(payload["F2"])
    
    solution = f"Tính lực tổng hợp vector (F_net):\n- F1 = {f1} N\n- F2 = {f2} N\n"
    
    if mode == "same_direction":
        ans = f1 + f2
        solution += f"Hai lực cùng chiều: F_net = F1 + F2 = {f1} + {f2} = {ans} N."
    elif mode == "opposite":
        ans = abs(f1 - f2)
        solution += f"Hai lực ngược chiều: F_net = |F1 - F2| = |{f1} - {f2}| = {ans} N."
    elif mode == "perpendicular":
        ans = math.sqrt(f1*f1 + f2*f2)
        solution += f"Hai lực vuông góc: F_net = sqrt(F1^2 + F2^2) = sqrt({f1}^2 + {f2}^2) = {ans:.4g} N."
    elif mode == "angle" or payload.get("mode") == "angle" or "alpha" in payload or payload.get("alpha") is not None:
        alpha = extract_val(payload.get("alpha", 60.0))
        rad = math.radians(alpha)
        ans = math.sqrt(f1*f1 + f2*f2 + 2*f1*f2*math.cos(rad))
        solution += f"Hai lực hợp nhau góc alpha = {alpha}°:\nF_net = sqrt(F1^2 + F2^2 + 2*F1*F2*cos(alpha)) = {ans:.4g} N."
    else:
        ans = f1 + f2
        solution += f"Không rõ chiều, mặc định cùng chiều: F_net = {ans} N."
        
    return {
        "success": True,
        "answer": ans,
        "answer_display": f"{ans:.4g} N",
        "formula_id": "vector_resultant",
        "equation": "vector_addition",
        "solution": solution,
    }

def _solve_angle(payload: dict) -> dict:
    if "F1" not in payload or "F2" not in payload or "F_net" not in payload:
        return {"success": False, "msg": "Missing F1, F2 or F_net in solve_angle payload"}
    f1 = float(payload["F1"]["value"] if isinstance(payload["F1"], dict) else payload["F1"])
    f2 = float(payload["F2"]["value"] if isinstance(payload["F2"], dict) else payload["F2"])
    f_net = float(payload["F_net"]["value"] if isinstance(payload["F_net"], dict) else payload["F_net"])
    
    cos_val = (f_net**2 - f1**2 - f2**2) / (2 * f1 * f2)
    cos_val = max(-1.0, min(1.0, cos_val))
    alpha = math.degrees(math.acos(cos_val))
    
    solution = (
        f"Tìm góc alpha giữa hai lực:\n"
        f"- F1 = {f1} N, F2 = {f2} N, F_net = {f_net} N\n"
        f"Từ công thức: F_net^2 = F1^2 + F2^2 + 2*F1*F2*cos(alpha)\n"
        f"cos(alpha) = (F_net^2 - F1^2 - F2^2) / (2*F1*F2) = {cos_val:.4f}\n"
        f"alpha = {alpha:.4g} độ"
    )
    return {
        "success": True,
        "answer": alpha,
        "answer_display": f"{alpha:.4g} Độ",
        "formula_id": "angle_from_resultant",
        "equation": "acos((R^2-F1^2-F2^2)/(2F1F2))",
        "solution": solution,
    }

def _solve_coulomb_layout(payload: dict) -> dict:
    charges = payload.get("charges", {})
    distances = payload.get("distances", {})
    target = payload.get("target_charge", "q3")
    quantity = payload.get("quantity", "force")
    is_collinear = (payload.get("layout") == "collinear") or (payload.get("task_type") == "coulomb_collinear")
    right_angle = payload.get("right_angle_at")
    
    k_const = 9.0e9  # Standard textbook constant used in this dataset
    
    q1 = charges.get("q1", 0.0)
    q2 = charges.get("q2", 0.0)
    q3 = charges.get("q3", charges.get("q0", 0.0))
    
    q_tgt = charges.get(target.lower(), 0.0) if quantity == "force" else 1.0
    
    # Normalize distances
    d12 = distances.get("q1_q2") or distances.get("q2_q1")
    d13 = distances.get("q1_q3") or distances.get("q3_q1") or distances.get("q1_q0") or distances.get("q0_q1") or distances.get("r1")
    d23 = distances.get("q2_q3") or distances.get("q3_q2") or distances.get("q2_q0") or distances.get("q0_q2") or distances.get("r2")
    
    if not is_collinear and d12 and d13 and d23:
        if abs(d13 + d23 - d12) < max(1e-5, 0.01 * d12) or abs(d13 + d12 - d23) < max(1e-5, 0.01 * d23) or abs(d23 + d12 - d13) < max(1e-5, 0.01 * d13):
            is_collinear = True
            
    if is_collinear:
        # Reconstruct missing collinear distances
        if d12 is not None and d13 is not None and d23 is None:
            if d13 < d12:
                d23 = d12 - d13
            else:
                d23 = d13 - d12
        elif d12 is not None and d23 is not None and d13 is None:
            if d23 < d12:
                d13 = d12 - d23
            else:
                d13 = d23 - d12
        elif d13 is not None and d23 is not None and d12 is None:
            d12 = d13 + d23

        x3 = 0.0
        if d12 is not None and d13 is not None and d23 is not None and abs(d13 + d23 - d12) < max(1e-5, 0.01 * d12):
            x1 = -d13
            x2 = d23
        elif d23 is not None and d12 is not None and d13 is not None and d13 < d23:
            x1 = d13
            x2 = d23
        elif d13 is not None and d12 is not None and d23 is not None and d23 < d13:
            x1 = -d13
            x2 = -d23
        else:
            x1 = -d13 if d13 is not None else -0.05
            x2 = d23 if d23 is not None else 0.05
            
        E1 = -k_const * q1 * x1 / (abs(x1)**3) if x1 != 0 else 0.0
        E2 = -k_const * q2 * x2 / (abs(x2)**3) if x2 != 0 else 0.0
        E_net = E1 + E2
        
        if quantity == "force":
            ans = abs(E_net * q_tgt)
            sol = (
                f"Giải hệ thẳng hàng (collinear 1D):\n"
                f"- q1 = {q1:.4g} C tại x = {x1:.4f} m\n"
                f"- q2 = {q2:.4g} C tại x = {x2:.4f} m\n"
                f"- Cường độ điện trường E1 = {E1:.4g} V/m\n"
                f"- Cường độ điện trường E2 = {E2:.4g} V/m\n"
                f"- E_net = {E_net:.4g} V/m\n"
                f"- Lực tác dụng tổng hợp F = |E_net * q_tgt| = {ans:.4g} N"
            )
        else:
            ans = abs(E_net)
            sol = (
                f"Giải hệ thẳng hàng (collinear 1D):\n"
                f"- q1 = {q1:.4g} C tại x = {x1:.4f} m\n"
                f"- q2 = {q2:.4g} C tại x = {x2:.4f} m\n"
                f"- Cường độ điện trường E1 = {E1:.4g} V/m\n"
                f"- Cường độ điện trường E2 = {E2:.4g} V/m\n"
                f"- Cường độ điện trường tổng hợp E = {ans:.4g} V/m"
            )
            
        return {
            "success": True,
            "answer": ans,
            "answer_display": f"{ans:.4g} N" if quantity == "force" else f"{ans:.4g} V/m",
            "formula_id": "coulomb_collinear_force" if quantity == "force" else "coulomb_collinear_field",
            "solution": sol
        }
        
    coords = {}
    if payload.get("center"):
        r12 = d12 or 0.1
        r = r12 / math.sqrt(3.0)
        coords["q1"] = (0.0, r)
        coords["q2"] = (-r12/2, -r/2)
        coords["q3"] = (r12/2, -r/2)
        coords["target"] = (0.0, 0.0)
        tx, ty = coords["target"]
    else:
        is_rt = right_angle or ("right" in payload.get("question", "").lower()) or ("vuông" in payload.get("question", "").lower())
        if is_rt:
            if d12 and d23 and not d13:
                d13 = math.sqrt(d12**2 + d23**2)
            elif d12 and d13 and not d23:
                d23 = math.sqrt(d12**2 + d13**2)
            elif d13 and d23 and not d12:
                d12 = math.sqrt(d13**2 + d23**2)
                
        if not d12: d12 = 0.1
        if not d13: d13 = 0.1
        if not d23: d23 = 0.1
        
        coords["q1"] = (0.0, 0.0)
        coords["q2"] = (d12, 0.0)
        
        cos_theta = (d12**2 + d13**2 - d23**2) / (2 * d12 * d13)
        cos_theta = max(-1.0, min(1.0, cos_theta))
        theta = math.acos(cos_theta)
        coords["q3"] = (d13 * cos_theta, d13 * math.sin(theta))
        
        coords["target"] = coords.get(target.lower(), coords["q3"])
        tx, ty = coords["target"]
        
    fx_net = 0.0
    fy_net = 0.0
    solution_steps = []
    solution_steps.append("Giải bài toán hình học Coulomb 2D:")
    
    for name in ["q1", "q2", "q3"]:
        if name == target.lower() and not payload.get("center"):
            continue
            
        cx, cy = coords[name]
        dx = tx - cx
        dy = ty - cy
        d = math.sqrt(dx*dx + dy*dy)
        if d < 1e-9:
            continue
            
        q_src = charges.get(name, 0.0)
        ux = dx / d
        uy = dy / d
        
        Ex = k_const * q_src * ux / (d**2)
        Ey = k_const * q_src * uy / (d**2)
        
        if quantity == "force":
            fx = Ex * q_tgt
            fy = Ey * q_tgt
            f_mag = math.sqrt(fx**2 + fy**2)
            fx_net += fx
            fy_net += fy
            solution_steps.append(f"- Tác dụng từ {name} ({q_src:.4g} C): fx={fx:.4g} N, fy={fy:.4g} N, độ lớn={f_mag:.4g} N")
        else:
            fx_net += Ex
            fy_net += Ey
            e_mag = math.sqrt(Ex**2 + Ey**2)
            solution_steps.append(f"- Điện trường từ {name} ({q_src:.4g} C): Ex={Ex:.4g} V/m, Ey={Ey:.4g} V/m, độ lớn={e_mag:.4g} V/m")
            
    ans = math.sqrt(fx_net**2 + fy_net**2)
    if quantity == "force":
        solution_steps.append(f"Tổng lực Net Force = {ans:.4g} N")
        return {
            "success": True,
            "answer": ans,
            "answer_display": f"{ans:.4g} N",
            "formula_id": "coulomb_geometry_force",
            "solution": "\n".join(solution_steps),
        }
    else:
        solution_steps.append(f"Tổng điện trường Net E-Field = {ans:.4g} V/m")
        return {
            "success": True,
            "answer": ans,
            "answer_display": f"{ans:.4g} V/m",
            "formula_id": "coulomb_geometry_field",
            "solution": "\n".join(solution_steps),
        }

def _solve_coulomb_bisector(payload: dict) -> dict:
    charges = payload.get("charges", {})
    ab = payload.get("ab_distance", 0.06)
    h = payload.get("bisector_distance", 0.04)
    quantity = payload.get("quantity", "force")
    
    k_const = 8.99e9
    q1 = charges.get("q1", 0.0)
    q2 = charges.get("q2", 0.0)
    q3 = charges.get("q3", 0.0)
    
    r = math.sqrt((ab/2)**2 + h**2)
    tx, ty = 0.0, h
    ax, ay = -ab/2, 0.0
    bx, by = ab/2, 0.0
    
    fx_net, fy_net = 0.0, 0.0
    
    for name, (cx, cy), q_src in [("q1", (ax, ay), q1), ("q2", (bx, by), q2)]:
        dx = tx - cx
        dy = ty - cy
        d = math.sqrt(dx*dx + dy*dy)
        
        f_mag = k_const * abs(q_src)
        if quantity == "force":
            f_mag *= abs(q3)
        f_mag /= (d**2)
        
        ux = dx / d
        uy = dy / d
        q_tgt = q3 if quantity == "force" else 1.0
        if (q_src * q_tgt) < 0:
            ux = -ux
            uy = -uy
            
        fx_net += f_mag * ux
        fy_net += f_mag * uy
        
    ans = math.sqrt(fx_net*fx_net + fy_net*fy_net)
    
    solution = (
        f"Giải hệ đường trung trực (bisector):\n"
        f"- ab = {ab} m, h = {h} m -> r = {r:.4g} m\n"
        f"- q1 = {q1} C, q2 = {q2} C\n"
    )
    if quantity == "force":
        solution += f"- q_test = {q3} C\nLực tổng hợp: F_net = {ans:.4g} N"
        return {
            "success": True,
            "answer": ans,
            "answer_display": f"{ans:.4g} N",
            "formula_id": "coulomb_bisector_force",
            "solution": solution,
        }
    else:
        solution += f"Cường độ điện trường tổng hợp: E_net = {ans:.4g} V/m"
        return {
            "success": True,
            "answer": ans,
            "answer_display": f"{ans:.4g} V/m",
            "formula_id": "coulomb_bisector_field",
            "solution": solution,
        }

def _solve_coulomb_field(payload: dict) -> dict:
    """Unified 1D coordinate-based electric field solver.

    Places charges on a number line and computes the signed field at point P:
        E_i = k * q_i * sign(x_P - x_i) / (x_P - x_i)^2
    The total field magnitude is |ΣE_i|.
    """
    charges = payload.get("charges", {})
    distances = payload.get("distances", {})

    k_const = 8.99e9
    q1 = charges.get("q1", 0.0)
    q2 = charges.get("q2", 0.0)

    r1 = distances.get("r1")
    r2 = distances.get("r2")
    r12 = distances.get("q1_q2")

    if r1 is not None and r2 is not None:
        # Point P sits between (or outside) q1 and q2 on a 1D axis.
        # Place q1 at 0, q2 at r12 (if known) or r1+r2.
        d_total = r12 if r12 else (r1 + r2)
        x1, x2, xP = 0.0, d_total, r1

        def _E_signed(q: float, xi: float, xp: float) -> float:
            dx = xp - xi
            if abs(dx) < 1e-12:
                return 0.0
            return k_const * q * (1.0 if dx > 0 else -1.0) / (dx ** 2)

        E_net = _E_signed(q1, x1, xP) + _E_signed(q2, x2, xP)
        ans = abs(E_net)
        sol = (
            f"Tính E bằng hệ tọa độ 1D:\n"
            f"- q1 = {q1:.4g} C tại x = {x1} m\n"
            f"- q2 = {q2:.4g} C tại x = {x2:.4g} m\n"
            f"- Điểm P tại x = {xP:.4g} m\n"
            f"- E1 = {_E_signed(q1,x1,xP):.4g} V/m, E2 = {_E_signed(q2,x2,xP):.4g} V/m\n"
            f"- E_net = {E_net:.4g} V/m → |E| = {ans:.4g} V/m"
        )
    else:
        r = r1 or r12 or 0.05
        ans = k_const * abs(q1) / (r ** 2)
        sol = f"E = k|q|/r² = {ans:.4g} V/m"

    return {
        "success": True,
        "answer": ans,
        "answer_display": f"{ans:.4g} V/m",
        "formula_id": "coulomb_field_1d",
        "solution": sol,
    }


def _solve_coulomb_equilibrium(payload: dict) -> dict:
    """Find the 1D point where the net electric field (or force) is zero.

    Searches in all three regions: left of q1, between q1 and q2, right of q2.
    Correctly handles same-sign (equilibrium between) and opposite-sign charges
    (equilibrium outside the segment).
    """
    charges = payload.get("charges", {})
    separation = float(payload.get("separation", 0.1))
    quantity = payload.get("quantity", "field")

    k_const = 8.99e9
    charge_items = list(charges.items())
    if len(charge_items) < 2:
        return {"success": False, "msg": "Need at least 2 charges for equilibrium"}

    q1_lbl, q1 = charge_items[0]
    q2_lbl, q2 = charge_items[1]
    L = separation  # q1 at x=0, q2 at x=L

    def net_field(xP: float) -> float:
        def E_i(q: float, xi: float) -> float:
            dx = xP - xi
            if abs(dx) < 1e-12:
                return float("inf")
            return k_const * q * (1.0 if dx > 0 else -1.0) / (dx ** 2)
        return E_i(q1, 0.0) + E_i(q2, L)

    def bisect(lo: float, hi: float, tol: float = 1e-9, max_iter: int = 200) -> Optional[float]:
        f_lo, f_hi = net_field(lo), net_field(hi)
        if math.isnan(f_lo) or math.isnan(f_hi):
            return None
        if f_lo * f_hi > 0:
            return None
        for _ in range(max_iter):
            mid = (lo + hi) / 2.0
            f_mid = net_field(mid)
            if abs(f_mid) < tol or (hi - lo) < tol:
                return mid
            if f_lo * f_mid < 0:
                hi = mid
                f_hi = f_mid
            else:
                lo = mid
                f_lo = f_mid
        return (lo + hi) / 2.0

    eps = L * 1e-4 + 1e-9
    candidates: list[tuple[float, str]] = []

    # Region left of q1
    x_left = bisect(-10 * L - eps, -eps)
    if x_left is not None:
        candidates.append((x_left, "left of q1"))

    # Region between q1 and q2
    x_mid = bisect(eps, L - eps)
    if x_mid is not None:
        candidates.append((x_mid, "between q1 and q2"))

    # Region right of q2
    x_right = bisect(L + eps, 10 * L + eps)
    if x_right is not None:
        candidates.append((x_right, "right of q2"))

    if not candidates:
        return {"success": False, "msg": "No equilibrium point found in any region"}

    # Pick the physically principal solution (smallest |E| residual)
    best_x, best_region = min(candidates, key=lambda t: abs(net_field(t[0])))

    # Express as distance from q1
    dist_from_q1 = best_x
    dist_from_q2 = L - best_x

    ans = abs(dist_from_q1)
    ans_display = f"{ans * 100:.4g} cm"

    sol = (
        f"Tìm điểm cân bằng điện trường/lực điện (equilibrium):\n"
        f"- {q1_lbl} = {q1:.4g} C tại x = 0 m\n"
        f"- {q2_lbl} = {q2:.4g} C tại x = {L:.4g} m\n"
        f"- Kiểm tra 3 vùng: left / between / right\n"
        f"- Điểm cân bằng: x = {best_x:.6g} m ({best_region})\n"
        f"- Cách {q1_lbl}: {dist_from_q1*100:.4g} cm, cách {q2_lbl}: {dist_from_q2*100:.4g} cm"
    )

    return {
        "success": True,
        "answer": ans,
        "answer_display": ans_display,
        "formula_id": "coulomb_equilibrium_1d",
        "solution": sol,
        "equilibrium_x": best_x,
        "region": best_region,
    }

def _solve_coulomb_pair(payload: dict) -> dict:
    charges = payload.get("charges", {})
    distances = payload.get("distances", {})
    
    k_const = 8.99e9
    q1 = charges.get("q1", 0.0)
    q2 = charges.get("q2", 0.0)
    r = distances.get("q1_q2") or 0.05
    
    ans = k_const * abs(q1 * q2) / (r**2)
    
    return {
        "success": True,
        "answer": ans,
        "answer_display": f"{ans:.4g} N",
        "formula_id": "coulomb_pair_force",
        "solution": f"Tính lực tương tác tĩnh điện Coulomb: F = k * |q1 * q2| / r^2 = {ans:.4g} N",
    }
