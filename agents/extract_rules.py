
import re
import math

def normalize_question_text(question: str) -> str:
    if not question:
        return ""
    return (
        question.replace("\\u03bc", "u")
        .replace("\\u00d7", "x")
        .replace("\\u2212", "-")
        .replace("\\u207b", "-")
        .replace("\u03bc", "u")
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("\u207b", "-")
        .replace("\u2212", "-")
        .replace("\u00b9", "1")
        .replace("\u00b2", "2")
        .replace("\u00b3", "3")
        .replace("\u00d7", "x")
        .replace("×", "x")
        .replace("\\times", "x")
        .replace("\\cdot", "x")
        .replace("·", "x")
    )

def _sci_charges_from_text(question: str) -> list[float]:
    question = normalize_question_text(question)
    out = []

    pat1 = r"([+-]?\d+(?:\.\d+)?)\s*(?:x|\*)\s*10\s*(?:\^|\*\*)\s*([-−\u2212\u207b]?)\s*\{?(\d+)\}?"
    for coeff_str, sign_str, exp_str in re.findall(pat1, question, re.I):
        try:
            coeff = float(coeff_str)
            exp = int(exp_str)

            if sign_str in ["-", "−", "\u2212", "\u207b"]:
                exp = -exp

            out.append(coeff * (10 ** exp))
        except:
            pass

    pat2 = r"(?<![\d.])10\s*(?:\^|\*\*)\s*([-−\u2212\u207b]?)\s*\{?(\d+)\}?"
    for sign_str, exp_str in re.findall(pat2, question, re.I):
        try:
            exp = int(exp_str)
            if sign_str in ["-", "−", "\u2212", "\u207b"]:
                exp = -exp
            out.append(10 ** exp)
        except:
            pass

    pat_e = r"([+-]?\d+(?:\.\d+)?[eE][+-]?\d+)\s*(?:(u|m|n|p)c|c)\b"
    for val_str, prefix in re.findall(pat_e, question, re.I):
        try:
            scale = {"u": 1e-6, "m": 1e-3, "n": 1e-9, "p": 1e-12, "": 1.0}
            out.append(float(val_str) * scale.get((prefix or "").lower(), 1.0))
        except:
            pass

    pat3 = r"\b(?:q[abc\d]?|q)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*(uc|mc|nc|pc|c)\b"
    for val_str, unit in re.findall(pat3, question, re.I):
        try:
            sign = -1 if val_str.startswith("-") else 1
            mag = float(val_str.lstrip("+-"))
            scale = {"uc": 1e-6, "mc": 1e-3, "nc": 1e-9, "pc": 1e-12, "c": 1.0}
            out.append(sign * mag * scale.get(unit.lower(), 1e-6))
        except:
            pass

    return out


def _has_charge_coulombs(question: str) -> bool:
    return len(_sci_charges_from_text(question)) >= 1

def _detect_target_label(q: str, charge_labels: list[str]) -> str:
    m = re.search(r"acting on (?:the charge at |point )?([ABC])\b", q, re.I)
    if m:
        return m.group(1).upper()

    m = re.search(r"force (?:acting )?on (?:the charge at )?([ABC])\b", q, re.I)
    if m:
        return m.group(1).upper()

    if "midpoint" in q or "trung điểm" in q:
        return "midpoint"

    if "q2" in q:
        return "q2"

    return charge_labels[-1] if charge_labels else "q3"


def complete_right_triangle_edges(edges: dict[tuple[str, str], float]) -> None:
    vertices = set()
    for u, v in edges.keys():
        vertices.add(u)
        vertices.add(v)
    if len(vertices) != 3:
        return
    v_list = list(vertices)
    pairs = [(v_list[0], v_list[1]), (v_list[1], v_list[2]), (v_list[2], v_list[0])]
    known = {}
    missing_pair = None
    for p in pairs:
        val = edges.get(p) or edges.get(p[::-1])
        if val:
            known[p] = val
        else:
            missing_pair = p
    if len(known) == 2 and missing_pair:
        vals = list(known.values())
        x, y = min(vals), max(vals)
        if abs(y**2 - x**2) > 1e-6:
            third = math.sqrt(y**2 - x**2)
            if y / x >= 1.2:
                val = third
            else:
                val = math.sqrt(x**2 + y**2)
        else:
            val = math.sqrt(x**2 + y**2)
        a, b = missing_pair
        edges[(a, b)] = val
        edges[(b, a)] = val

def _parse_vertex_edges(question: str) -> dict[tuple[str, str], float]:
    question = normalize_question_text(question)
    scale = {"cm": 0.01, "m": 1.0, "mm": 0.001}
    edges: dict[tuple[str, str], float] = {}

    # Parse edge chains like: AC = BC = 12 cm  or  AB = BC = CA = 10 cm
    chain_pat = re.compile(
        r"\b((?:[A-Za-z]{2}\s*=\s*){1,5})([\d.]+)\s*(cm|m|mm)\b", re.I
    )
    for cm in chain_pat.finditer(question):
        dist = float(cm.group(2)) * scale.get(cm.group(3).lower(), 1.0)
        segments = re.findall(r"[A-Za-z]{2}", cm.group(1))
        for seg in segments:
            a, b = seg[0].upper(), seg[1].upper()
            if a != b:
                edges[(a, b)] = dist
                edges[(b, a)] = dist

    for m in re.finditer(r"\b([A-Za-z])\s*([A-Za-z])\s*=\s*([\d.]+)\s*(cm|m|mm)\b", question, re.I):
        a, b = m.group(1).upper(), m.group(2).upper()
        if a == b:
            continue
        d = float(m.group(3)) * scale.get(m.group(4).lower(), 1.0)
        edges[(a, b)] = d
        edges[(b, a)] = d

    for m in re.finditer(r"points?\s+([A-Za-z])\s+and\s+([A-Za-z])\s+are\s+separated\s+by\s+([\d.]+)\s*(cm|m|mm)", question, re.I):
        a, b = m.group(1).upper(), m.group(2).upper()
        d = float(m.group(3)) * scale.get(m.group(4).lower(), 1.0)
        edges[(a, b)] = d
        edges[(b, a)] = d

    for m in re.finditer(r"\b([A-Za-z])\s*and\s*([A-Za-z])\b.*?\b([\d.]+)\s*(cm|m|mm)\s*apart", question, re.I):
        a, b = m.group(1).upper(), m.group(2).upper()
        d = float(m.group(3)) * scale.get(m.group(4).lower(), 1.0)
        edges[(a, b)] = d
        edges[(b, a)] = d

    if "right-angled" in question.lower() or "right angled" in question.lower() or "vuông" in question.lower():
        complete_right_triangle_edges(edges)

    return edges

def classify_topic_prefix(q_id: str) -> str:
    m = re.match(r"([A-Za-z]+)", str(q_id or ""))
    if not m:
        return "UNKNOWN"
    pref = m.group(1).upper()
    topic_map = {
        "CH": "CH", "CHLT": "CH", "TD": "TD", "LD": "LD",
        "DT": "DT", "DDT": "DDT", "NL": "NL", "DD": "DD",
        "TH": "TH", "THCB": "TH"
    }
    return topic_map.get(pref, pref)

def classify_task_type(question: str) -> str:
    q = normalize_question_text(question).lower()

    if "coulomb force" in q:
        return "coulomb_geometry"

    if "midpoint" in q or "trung điểm" in q:
        return "coulomb_collinear"

    if "electric field" in q or "điện trường" in q:
        return "coulomb_geometry"

    return "algebraic"


    # Equilibrium: net field/force = 0, find the balance point.
    # Check before generic field/geometry branches.
    _eq_plain = ("triệt tiêu", "bằng 0", "cân bằng", "equilibrium", "cancel out")
    _eq_regex = (
        r"net\s+(?:electric\s+)?(?:force|field)\s+(?:is\s+)?zero",
        r"zero\s+(?:net\s+)?(?:electric\s+)?(?:force|field)",
        r"where\s+.{0,60}(?:zero|null|triệt tiêu|bằng 0)",
        r"(?:electric\s+)?(?:force|field)\s+(?:is\s+)?zero",
        r"(?:force|field)\s+.{0,30}(?:zero|null)\b",
        r"cường\s+độ\s+điện\s+trường\s+.{0,30}bằng\s+0",
        r"điện\s+trường\s+.{0,30}triệt\s+tiêu",
        r"lực\s+tổng\s+hợp\s+.{0,30}bằng\s+0",
    )
    if has_coulomb_data and (
        any(kw in q for kw in _eq_plain)
        or any(bool(re.search(rx, q)) for rx in _eq_regex)
    ):
        return "coulomb_equilibrium"
    if re.search(r"\bfind\s+(?:the\s+)?(?:charge\s+)?q\b", q) and ("separated by" in q or "exert a force" in q or "q1 = q2" in q):
        return "algebraic"
    if re.search(r"\bfind\s+(?:the\s+)?angle\b", q) and "resultant" in q:
        return "solve_angle"
    if "perpendicular bisector" in q or "đường trung trực" in q:
        return "coulomb_bisector"
    if re.search(r"electric fields?.*\d+\s*(?:°|deg)", q) or ("angle of" in q and "electric field" in q):
        return "coulomb_field_angle"
    if "midpoint" in q or "trung điểm" in q:
        return "coulomb_collinear"

    if re.search(r"\b([abc])\s*([abc])\s*=\s*[\d.]+\s*(?:cm|m|mm)\b", q, re.I) or re.search(r"\b(?:ac|bc|ca|cb|ab)\s*=", q):
        if has_coulomb_data or "charge" in q or "điện tích" in q:
            return "coulomb_geometry"

    if re.search(r"\d+(?:\.\d+)?\s*cm\s+from\s+a\b", q) and re.search(r"\d+(?:\.\d+)?\s*cm\s+from\s+b\b", q):
        if not re.search(r"\b(?:ac|bc|ca|cb)\s*=", q):
            return "coulomb_collinear"

    if "electric field" in q and ("midpoint" in q or "trung điểm" in q):
        return "coulomb_collinear"
    if "electric field" in q and "net force" not in q and "resultant force" not in q and "force acting" not in q:
        return "coulomb_field"
    if re.search(r"force\s+(?:acting\s+)?on\s+q\d+\s+by\s+q\d+", q) or ("by q2" in q and "acting on q1" in q):
        return "coulomb_pair"

    forces_n = re.findall(r"([\d.]+)\s*n\b", q)
    distinct_forces = len(set(forces_n)) >= 2
    angle_vector = ("act at an angle" in q or "angle of" in q or "góc" in q) and len(forces_n) >= 2
    vector_hints = (distinct_forces or angle_vector or "each" in q) and (
        "resultant force" in q or "acting in the same direction" in q or angle_vector
        or "two electric forces" in q or ("forces" in q and "perpendicular to each other" in q)
        or ("electric forces" in q and "magnitude" in q) or "lực tổng hợp" in q
    )
    if vector_hints and not has_coulomb_data:
        return "vector_resultant"

    if "straight line" in q or "collinear" in q or "cùng một đường thẳng" in q or "thẳng hàng" in q:
        if has_coulomb_data or ("charge" in q and "cm" in q):
            return "coulomb_collinear"

    coulomb_hints = (
        has_coulomb_data or ("three" in q and "charge" in q)
        or ("two charges" in q and ("third charge" in q or "test charge" in q))
        or ("point charge" in q and "placed at" in q) or ("vertices" in q and "triangle" in q)
    )
    if coulomb_hints:
        return "coulomb_geometry"

    return "algebraic"

def extract_td_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()

    c_m = (
        re.search(r"c\s*=\s*([\d.]+)\s*(pf|nf|uf|f)\b", q, re.I)
        or re.search(r"capacitance of ([\d.]+)\s*(pf|nf|uf|f)\b", q, re.I)
        or re.search(r"capacitance of ([\d.]+)\s*(pf|nf|uf)\b", q, re.I)
        or re.search(r"has a capacitance of ([\d.]+)\s*(pf|nf|uf)\b", q, re.I)
        or re.search(r"điện dung\s*([\d.]+)\s*(pf|nf|uf|f)\b", q, re.I)
    )
    u_m = (
        re.search(r"(?:potential difference|voltage|charged to|hiệu điện thế|điện áp)\s*(?:of\s*)?(?:a\s*)?(?:u\s*=\s*)?([\d.]+)\s*v\b", q, re.I)
        or re.search(r"\bu\s*=\s*([\d.]+)\s*v\b", q, re.I)
        or re.search(r"(?:voltage|potential difference|hiệu điện thế).*?([\d.]+)\s*v\b", q, re.I)
    )
    eps_m = re.search(
        r"(?:dielectric constant|relative permittivity|permittivity|epsilon|hằng số điện môi)\s*(?:of\s*)?(?:ε_r\s*=\s*|ε\s*=\s*|kappa\s*=\s*|k\s*=\s*)?([\d.]+)", q, re.I,
    ) or re.search(r"ε\s*=\s*([\d.]+)", q, re.I)

    if not c_m:
        return None

    knowns = {"C": {"value": float(c_m.group(1)), "unit": c_m.group(2)}}
    if u_m:
        knowns["U"] = {"value": float(u_m.group(1)), "unit": "V"}
    if eps_m:
        knowns["epsilon"] = {"value": float(eps_m.group(1)), "unit": "1"}

    disconnected = "disconnected" in q or "ngắt khỏi" in q or "ngắt nguồn" in q
    connected = ("still connected" in q or "remains connected" in q or "vẫn nối" in q or "vẫn cắm" in q or ("connected" in q and not disconnected))

    if "energy" in q or "năng lượng" in q:
        target = "E"
    elif "doubled" in q and "distance" in q and "capacitance" in q:
        target = "C1"
    elif "doubled" in q and "distance" in q and "potential" in q:
        target = "U1"
    elif "dielectric" in q or eps_m:
        target = "U_new"
    elif "capacitance" in q and re.search(r"\bc1\b", q):
        target = "C1"
    elif "potential" in q and re.search(r"\bu1\b", q):
        target = "U1"
    elif "charge" in q or "điện tích" in q:
        target = "Q"
    elif "capacitance" in q or "điện dung" in q:
        target = "C"
    else:
        target = "U_new"

    if target == "E" and eps_m:
        knowns["_dielectric_mode"] = {"value": 1 if connected else 0, "unit": "connected" if connected else "disconnected"}
    if target == "U_new" and eps_m:
        knowns["_dielectric_mode"] = {"value": 1 if (connected and not disconnected) else 0, "unit": "connected" if (connected and not disconnected) else "disconnected"}

    if re.search(r"c1\s*=\s*([\d.]+)\s*(uf|nf|pf)", q) and re.search(r"c2\s*=\s*([\d.]+)\s*(uf|nf|pf)", q):
        c1m = re.search(r"c1\s*=\s*([\d.]+)\s*(uf|nf|pf)", q, re.I)
        c2m = re.search(r"c2\s*=\s*([\d.]+)\s*(uf|nf|pf)", q, re.I)
        knowns["C1"] = {"value": float(c1m.group(1)), "unit": c1m.group(2)}
        knowns["C2"] = {"value": float(c2m.group(1)), "unit": c2m.group(2)}
        target = "C"
        if "series" in q or "nối tiếp" in q:
            knowns["_cap_layout"] = {"value": 0, "unit": "series"}
        elif "parallel" in q or "song song" in q:
            knowns["_cap_layout"] = {"value": 1, "unit": "parallel"}

    return {"task_type": "algebraic", "target": target, "knowns": knowns}

def extract_algebraic_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    td = extract_td_rulebased(question)
    if td:
        return td

    if "energy stored" in q or "năng lượng" in q or ("capacitor" in q and re.search(r"\b[uc]\s*=", q)):
        c_m = re.search(r"c\s*=\s*([\d.]+)\s*(?:u)?f\b", q, re.I)
        u_m = re.search(r"u\s*=\s*([\d.]+)\s*v\b", q, re.I)
        if c_m and u_m:
            return {"task_type": "algebraic", "target": "E", "knowns": {"C": {"value": float(c_m.group(1)), "unit": "uf"}, "U": {"value": float(u_m.group(1)), "unit": "V"}}}

    if ("capacitance" in q or "điện dung" in q) and re.search(r"q\s*=", q):
        q_m = re.search(r"q\s*=\s*([\d.]+)\s*(mc|μc|µc|uc|c)\b", q, re.I)
        u_m = re.search(r"u\s*=\s*([\d.]+)\s*v\b", q, re.I)
        if q_m and u_m:
            return {"task_type": "algebraic", "target": "C", "knowns": {"Q": {"value": float(q_m.group(1)), "unit": q_m.group(2)}, "U": {"value": float(u_m.group(1)), "unit": "V"}}}

    if re.search(r"\bfind\s+(?:the\s+)?(?:charge\s+)?q\b", q) or "tìm điện tích q" in q:
        f_m = re.search(r"(?:force|lực)\s+(?:of|là)?\s*([\d.]+)\s*n\b", q, re.I)
        r_m = re.search(r"(?:separated by|khoảng cách|cách nhau)\s+([\d.]+)\s*(cm|m|mm)\b", q, re.I)
        if f_m and r_m:
            scale = {"cm": 0.01, "m": 1.0, "mm": 0.001}
            r_val = float(r_m.group(1)) * scale.get(r_m.group(2).lower(), 1.0)
            return {"task_type": "algebraic", "target": "q", "knowns": {"F": {"value": float(f_m.group(1)), "unit": "N"}, "r": {"value": r_val, "unit": "m"}}}

    plate = extract_parallel_plate_rulebased(question)
    if plate:
        return plate
    return None

def extract_parallel_plate_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    area = re.search(r"plate area of ([\d.]+)\s*cm", q) or re.search(r"area of ([\d.]+)\s*cm", q) or re.search(r"diện tích\s*([\d.]+)\s*cm", q)
    sep = re.search(r"(?:plate )?separation of ([\d.]+)\s*(mm|cm|m)", q) or re.search(r"(?:separated by|khoảng cách|cách nhau)\s*([\d.]+)\s*(mm|cm|m)", q)
    if not area or not sep:
        return None
    target = "C"
    if "charge" in q and "capacitance" not in q:
        target = "Q"
    return {"task_type": "algebraic", "target": target, "knowns": {"S": {"value": float(area.group(1)), "unit": "cm2"}, "d": {"value": float(sep.group(1)), "unit": sep.group(2)}}}

def extract_field_angle_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    if "electric field" not in q and "điện trường" not in q:
        return None
    vals = _sci_charges_from_text(question)
    dist = re.search(r"([\d.]+)\s*cm\s+from\s+point\s+m", q) or re.search(r"([\d.]+)\s*cm\s+from\s+m\b", q) or re.search(r"cách\s+m\s+([\d.]+)\s*cm", q)
    ang = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|deg|degrees|độ)\b", question, re.I)
    if len(vals) < 2 or not dist:
        return None
    return {"task_type": "coulomb_field_angle", "charges": {"q1": vals[0], "q2": vals[1]}, "distance_m": float(dist.group(1)) * 0.01, "angle_deg": float(ang.group(1)) if ang else 60.0}

def extract_pair_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    if "by q2" not in q and "by q1" not in q and "tác dụng lên" not in q:
        return None
    charges_uc = re.findall(r"q\d+\s*=\s*([+-]?\d+(?:\.\d+)?)\s*(?:u)?c\b", q, re.I)
    sep = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+apart", q) or re.search(r"(?:separated by|khoảng cách|cách nhau)\s*(?:a distance of\s*)?(\d+(?:\.\d+)?)\s*cm", q)
    if len(charges_uc) < 2 or not sep:
        return None
    def parse_uc(s: str) -> float:
        s = s.strip()
        sign = -1 if s.startswith("-") else 1
        return sign * float(s.lstrip("+-")) * 1e-6
    return {"task_type": "coulomb_pair", "charges": {"q1": parse_uc(charges_uc[0]), "q2": parse_uc(charges_uc[1])}, "distances": {"q1_q2": float(sep.group(1)) * 0.01}}

def extract_field_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    if "electric field" not in q and "điện trường" not in q:
        return None
    vals = _sci_charges_from_text(question)
    sep = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+apart", q) or re.search(r"cách nhau\s*([\d.]+)\s*cm", q)
    from_a = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+from\s+a\b", q) or re.search(r"cách\s+a\s*([\d.]+)\s*cm", q)
    from_b = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+from\s+b\b", q) or re.search(r"cách\s+b\s*([\d.]+)\s*cm", q)
    if len(vals) < 2:
        return None
    dist = {}
    if sep:
        dist["q1_q2"] = float(sep.group(1)) * 0.01
    if from_a and from_b:
        dist["r1"] = float(from_a.group(1)) * 0.01
        dist["r2"] = float(from_b.group(1)) * 0.01
    elif sep:
        dist["q1_q2"] = float(sep.group(1)) * 0.01
    else:
        return None
    return {"task_type": "coulomb_field", "charges": {"q1": vals[0], "q2": vals[1]}, "distances": dist}

def _edge_len(edges: dict, a: str, b: str) -> float | None:
    return edges.get((a, b)) or edges.get((b, a))

def _detect_target_label(q: str, charge_labels: list[str]) -> str:
    m = re.search(r"acting on (?:the charge at |point )?([ABC])\b", q, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"force (?:acting )?on (?:the charge at )?([ABC])\b", q, re.I)
    if m:
        return m.group(1).upper()
    if re.search(r"acting on q2|force on q2|on q2\b", q):
        return "q2"
    if "test charge" in q or "third charge" in q or "on q3" in q or "acting on q3" in q:
        if "q3" in charge_labels:
            return "q3"
    if "q3" in charge_labels:
        return "q3"
    return charge_labels[-1] if charge_labels else "q3"

def extract_labeled_triangle_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    charges_raw = {k.lower(): v for k, v in _parse_individual_charges(question).items()}
    if len(charges_raw) < 3:
        return None
    edges = _parse_vertex_edges(question)
    labels = list(charges_raw.keys())

    charge_to_vertex: dict[str, str] = {}
    for m in re.finditer(r"\b(q[a-z\d])\b[^.]{1,50}?\b(?:at|placed at)\s+point\s+([ABC])\b", q, re.I):
        charge_to_vertex[m.group(1).lower()] = m.group(2).upper()
    for m in re.finditer(r"\b(q[a-z\d])\b[^.]{1,50}?\b(?:at|placed at)\s+([ABC])\b", q, re.I):
        charge_to_vertex.setdefault(m.group(1).lower(), m.group(2).upper())

    m = re.search(r"\bq1\b.*?\bq2\b.*?\bpoints?\s+([ABC])\s+and\s+([ABC])\b", q, re.I)
    if m:
        charge_to_vertex.setdefault("q1", m.group(1).upper())
        charge_to_vertex.setdefault("q2", m.group(2).upper())
    m = re.search(r"\bq1\b\s*and\s*\bq2\b.*?\bplaced\s+at\s+([ABC])\s+and\s+([ABC])\b", q, re.I)
    if m:
        charge_to_vertex.setdefault("q1", m.group(1).upper())
        charge_to_vertex.setdefault("q2", m.group(2).upper())
    m = re.search(r"\bq3\b.*?\bpoint\s+([ABC])\b", q, re.I)
    if m:
        charge_to_vertex.setdefault("q3", m.group(1).upper())

    # Fallback mappings: sorted order matching vertices A, B, C
    if not charge_to_vertex or len(charge_to_vertex) < 3:
        for label in sorted(labels):
            v_char = label.replace("q", "").upper()
            if v_char in ("A", "B", "C"):
                charge_to_vertex.setdefault(label, v_char)

    # Sequential fallback for any leftover charges
    ordered_labels = [l for l in ("q1", "q2", "q3") if l in labels] + [l for l in labels if l not in ("q1", "q2", "q3")]
    for i, l in enumerate(ordered_labels):
        v = ("A", "B", "C")[i % 3]
        charge_to_vertex.setdefault(l, v)

    vertex_to_charge: dict[str, str] = {v: k for k, v in charge_to_vertex.items()}
    target_lbl = _detect_target_label(q, labels).lower()

    if target_lbl not in charges_raw:
        if target_lbl.upper() in vertex_to_charge:
            target_lbl = vertex_to_charge[target_lbl.upper()]
        else:
            mapping = {"a": "q1", "b": "q2", "c": "q3"}
            alt_tgt = mapping.get(target_lbl, target_lbl)
            if alt_tgt in charges_raw:
                target_lbl = alt_tgt
            elif f"q{target_lbl}" in charges_raw:
                target_lbl = f"q{target_lbl}"
            elif target_lbl in ("a", "b", "c") and all(x in labels for x in ("q1", "q2", "q3")):
                target_lbl = "q3"
            else:
                target_lbl = "q3"

    others = [k for k in labels if k != target_lbl][:2]
    if len(others) < 2:
        return None
    o1, o2 = others[0], others[1]
    t = target_lbl

    mapping = {o1: "q1", o2: "q2", t: "q3"}
    if vertex_to_charge and all(v in vertex_to_charge for v in ("A", "B", "C")):
        mapping = {vertex_to_charge["A"].lower(): "q1", vertex_to_charge["B"].lower(): "q2", vertex_to_charge["C"].lower(): "q3"}

    charges = {mapping[k]: charges_raw[k] for k in (o1, o2, t) if k in charges_raw}

    def map_edge(a: str, b: str) -> str | None:
        c_a = vertex_to_charge.get(a.upper())
        c_b = vertex_to_charge.get(b.upper())
        if c_a and c_b:
            c_a = c_a.lower()
            c_b = c_b.lower()
            if c_a in mapping and c_b in mapping:
                k_a = mapping[c_a]
                k_b = mapping[c_b]
                if k_a > k_b:
                    k_a, k_b = k_b, k_a
                return f"{k_a}_{k_b}"
        return None

    dist: dict[str, float] = {}
    for (a, b), d in edges.items():
        key = map_edge(a, b)
        if key:
            dist[key] = d

    d_t1 = _edge_len(edges, t, o1) or dist.get(f"q3_q1") or dist.get("q1_q3")
    d_t2 = _edge_len(edges, t, o2) or dist.get(f"q3_q2") or dist.get("q2_q3")
    d_12 = _edge_len(edges, o1, o2) or dist.get("q1_q2")
    if d_t1:
        dist[f"q1_q3"] = d_t1
        dist[f"q3_q1"] = d_t1
    if d_t2:
        dist[f"q2_q3"] = d_t2
        dist[f"q3_q2"] = d_t2
    if d_12:
        dist["q1_q2"] = d_12

    collinear = False
    if d_t1 and d_t2 and d_12:
        collinear = abs((d_t1 + d_t2) - d_12) < max(1e-6, 0.01 * d_12)
    if "right-angled" in q or "right angled" in q or "vuông" in q:
        collinear = False

    payload = {
        "task_type": "coulomb_collinear" if collinear else "coulomb_geometry",
        "target_charge": mapping.get(t, "q3"),
        "charges": charges,
        "distances": dist,
    }
    if collinear:
        payload["layout"] = "collinear"

    if "right-angled" in q or "right angled" in q or "vuông" in q:
        payload["right_angle_at"] = "B" if "B" in labels else None

    if not collinear and len(dist) < 2:
        return None
    if "electric field" in q or "điện trường" in q:
        payload["quantity"] = "field"
    return normalize_coulomb_payload(payload, question)

def _parse_individual_charges(question: str) -> dict[str, float]:
    """Parse individual charge assignments including chain notation.

    Supports:
    - q1 = q2 = q3 = 1e-9 C  (equal chain)
    - q1 = -q2 = 6 uC         (sign-alternating chain)
    - qA = qB = qC = 4 uC     (letter-index labels common in geometry problems)
    """
    question = normalize_question_text(question)
    q = question.lower()
    out: dict[str, float] = {}

    # --- Equal-value charge chains: q1 = q2 = q3 = VALUE UNIT ---
    # Handles: VALUE = x*10^N C  or  VALUE e-N C  or  plain VALUE [prefix]C
    chain_eq_pat = re.compile(
        r"\b((?:q[a-z\d]\s*=\s*){2,})"   # two or more qX = groups
        r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?:\s*(?:x|\*)\s*10\s*\^?\s*[-−]?\d+)?)"  # value
        r"\s*(m|u|μ|µ|n|p|uc|mc|nc|pc)?c\b",
        re.I,
    )
    for cm in chain_eq_pat.finditer(q):
        labels = re.findall(r"q[a-z\d]", cm.group(1), re.I)
        raw_val = cm.group(2).replace(" ", "")
        unit = (cm.group(3) or "").lower().rstrip("c") or ""
        scale_map = {"m": 1e-3, "u": 1e-6, "μ": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "": 1.0}
        # Evaluate possible sci notation inside value string (x*10^N form)
        sci = re.match(r"([+-]?\d+(?:\.\d+)?)\s*(?:x|\*)\s*10\s*\^?\s*([-−]?\d+)", raw_val)
        if sci:
            base = float(sci.group(1))
            exp = int(sci.group(2).replace("−", "-"))
            val = base * (10 ** exp)
        else:
            val = float(raw_val)  # handles both plain and 1e-9 notation
        val *= scale_map.get(unit, 1.0)
        for lbl in labels:
            out[lbl.lower()] = val

    # --- Sign-alternating chain: q1 = -q2 = VALUE UNIT  or  -q1 = q2 = VALUE UNIT ---
    chain_alt_pat = re.compile(
        r"((?:[+-]?\s*q[a-z\d]\s*=\s*){2,})"
        r"([+-]?\d+(?:\.\d+)?(?:\s*(?:x|\*)\s*10\s*\^?\s*[-−]?\d+)?)"
        r"\s*(m|u|μ|µ|n|p|uc|mc|nc|pc)?c\b",
        re.I,
    )
    for cm in chain_alt_pat.finditer(q):
        tokens = re.findall(r"([+-]?)\s*(q[a-z\d])", cm.group(1), re.I)
        if not tokens:
            continue
        raw_val = cm.group(2).replace(" ", "")
        unit = (cm.group(3) or "").lower().rstrip("c") or ""
        scale_map = {"m": 1e-3, "u": 1e-6, "μ": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "": 1.0}
        sci = re.match(r"([+-]?\d+(?:\.\d+)?)\s*(?:x|\*)\s*10\s*\^?\s*([-−]?\d+)", raw_val)
        if sci:
            base = float(sci.group(1))
            exp = int(sci.group(2).replace("−", "-"))
            mag = abs(base) * (10 ** exp)
        else:
            mag = abs(float(raw_val))
        mag *= scale_map.get(unit, 1.0)
        # First token sign determines anchor magnitude, subsequent signs relative to chain sign
        first_sign = -1 if tokens[0][0] == "-" else 1
        for i, (sgn_str, lbl) in enumerate(tokens):
            sgn = -1 if sgn_str == "-" else 1
            # Relative to first token: if same sign as first → positive value, else negative
            final_val = first_sign * sgn * mag if i > 0 else first_sign * mag
            out.setdefault(lbl.lower(), final_val)

    # --- Standard individual: qX = VALUE UNIT ---
    for m in re.finditer(r"\b(q[a-z\d]?)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*(?:x|\*|×)?\s*10\s*\^?\s*[-−]?\s*(\d+)\s*c\b", q, re.I):
        out.setdefault(m.group(1).lower(), float(m.group(2)) * (10 ** -int(m.group(3))))

    for m in re.finditer(r"\b(q[a-z\d]?)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*(m|u|μ|µ|n|p)?c\b", q, re.I):
        name = m.group(1).lower()
        val_str = m.group(2)
        unit = (m.group(3) or "").lower()
        scale = {"m": 1e-3, "u": 1e-6, "μ": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "": 1.0}
        sign = -1 if val_str.startswith("-") else 1
        mag = float(val_str.lstrip("+-"))
        out.setdefault(name, sign * mag * scale.get(unit, 1.0))

    if len(out) < 3:
        vals = _sci_charges_from_text(question)
        if len(vals) >= 3:
            out = {"q1": vals[0], "q2": vals[1], "q3": vals[2]}

    return out

def extract_equilibrium_rulebased(question: str) -> dict | None:
    """Parse a Coulomb equilibrium problem (net field/force = 0).

    Returns a payload with task_type='coulomb_equilibrium', charges dict,
    and the separation distance between the two source charges.
    """
    question = normalize_question_text(question)
    q = question.lower()

    charges_raw = _parse_individual_charges(question)
    vals = _sci_charges_from_text(question)

    # Need at least two source charges
    if len(charges_raw) >= 2:
        charge_list = list(charges_raw.items())
        q1_lbl, q1_val = charge_list[0]
        q2_lbl, q2_val = charge_list[1]
    elif len(vals) >= 2:
        q1_lbl, q1_val = "q1", vals[0]
        q2_lbl, q2_val = "q2", vals[1]
    else:
        return None

    # Parse separation distance
    sep_m = (
        re.search(r"(\d+(?:\.\d+)?)\s*(cm|m|mm)\s+apart", q)
        or re.search(r"cách nhau\s*([\d.]+)\s*(cm|m|mm)", q)
        or re.search(r"separated by\s*([\d.]+)\s*(cm|m|mm)", q)
    )
    scale = {"m": 1.0, "cm": 0.01, "mm": 0.001}
    separation = float(sep_m.group(1)) * scale.get(sep_m.group(2).lower(), 1.0) if sep_m else 0.1

    quantity = "field" if ("electric field" in q or "điện trường" in q) else "force"

    return {
        "task_type": "coulomb_equilibrium",
        "charges": {q1_lbl: q1_val, q2_lbl: q2_val},
        "separation": separation,
        "quantity": quantity,
    }


def extract_collinear_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()

    labeled = extract_labeled_triangle_rulebased(question)
    if labeled and labeled.get("layout") == "collinear":
        return labeled

    ind = _parse_individual_charges(question)
    if len(ind) >= 3 and all(k in ind for k in ("q1", "q2", "q3")):
        vals = [ind["q1"], ind["q2"], ind["q3"]]
    elif len(ind) >= 3:
        vals = list(ind.values())[:3]
    else:
        vals = _sci_charges_from_text(question)

    m_sym = re.search(r"q1\s*=\s*-?\s*q2\s*=\s*10\s*\^?\s*[-−]?\s*(\d+)\s*c", q, re.I)
    if m_sym:
        mag = 10 ** -int(m_sym.group(1))
        neg_first = bool(re.search(r"q1\s*=\s*-\s*q2\s*=", q, re.I))
        vals = [-mag, mag] if neg_first else [mag, -mag]
        q0m = re.search(r"q0\s*=\s*10\s*\^?\s*[-−]?\s*(\d+)\s*c", q, re.I)
        if q0m:
            vals.append(10 ** -int(q0m.group(1)))

    if len(vals) < 3:
        charges_uc = re.findall(r"([+-]?\d+(?:\.\d+)?)\s*(?:u)?c\b", q, re.I)
        c_vals = []
        for c in charges_uc:
            sign = -1 if c.startswith("-") else 1
            c_vals.append(sign * float(c.lstrip("+-")) * 1e-6)
        if len(c_vals) >= 3:
            vals = c_vals
        elif len(c_vals) == 2 and "two" in q:
            vals = [c_vals[0], c_vals[1], c_vals[1]]
        elif "q" in ind and len(vals) == 2:
            vals.append(ind["q"])
        elif "Q" in ind and len(vals) == 2:
            vals.append(ind["Q"])

    if len(vals) < 3:
        return None
    vals = vals[:3]

    target = "q0" if "q0" in q else "q3"
    if "on q2" in q or "acting on q2" in q or "force acting on q2" in q:
        target = "q2"
    if "from q" in q or "acting on q " in q:
        target = "q"

    dist = {}
    dist_from_q = re.search(r"distances of ([\d.]+)\s*(cm|m|mm) and ([\d.]+)\s*(cm|m|mm)(?:\s+respectively)?\s+from", q) or re.search(r"khoảng cách.*?([\d.]+)\s*(cm|m|mm).*?([\d.]+)\s*(cm|m|mm)", q)
    if dist_from_q:
        scale1 = {"m": 1.0, "cm": 0.01, "mm": 0.001}.get(dist_from_q.group(2), 1.0)
        scale2 = {"m": 1.0, "cm": 0.01, "mm": 0.001}.get(dist_from_q.group(4), 1.0)
        r1 = float(dist_from_q.group(1)) * scale1
        r2 = float(dist_from_q.group(3)) * scale2
        dist = {f"q1_{target}": r1, f"q2_{target}": r2, "q1_q2": r1 + r2}

    elif "apart" in q and ("straight line" in q or "three charges" in q):
        sep = re.search(r"([\d.]+)\s*(cm|m|mm)\s+apart", q) or re.search(r"cách nhau\s*([\d.]+)\s*(cm|m|mm)", q)
        if sep:
            scale = {"m": 1.0, "cm": 0.01, "mm": 0.001}.get(sep.group(2), 1.0)
            a = float(sep.group(1)) * scale
            if target == "q2":
                dist = {"q1_q2": a, "q2_q3": a, "q1_q3": 2*a}
            else:
                dist = {"q1_q2": a, f"q2_{target}": a, f"q1_{target}": 2*a}

    if not dist:
        from_ab = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+from\s+a\b", q) or re.search(r"cách\s+a\s*([\d.]+)\s*cm", q)
        from_b = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+from\s+b\b", q) or re.search(r"cách\s+b\s*([\d.]+)\s*cm", q)
        sep = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+apart", q) or re.search(r"cách nhau\s*([\d.]+)\s*cm", q)
        d_total = float(sep.group(1)) * 0.01 if sep else 0.1
        if from_ab and from_b:
            r1 = float(from_ab.group(1)) * 0.01
            r2 = float(from_b.group(1)) * 0.01
            d_total = max(d_total, r1 + r2) if sep else r1 + r2
            dist = {f"q1_{target}": r1, f"q2_{target}": r2, "q1_q2": d_total}
        else:
            dist = {f"q1_{target}": d_total / 2.0, f"q2_{target}": d_total / 2.0, "q1_q2": d_total}

    if target == "q":
        c_dict = {"q1": vals[1], "q2": vals[2], target: vals[0]}
    else:
        c_dict = {"q1": vals[0], "q2": vals[1], target: vals[2]}

    payload = {
        "task_type": "coulomb_collinear",
        "target_charge": target,
        "charges": c_dict,
        "distances": dist,
        "layout": "collinear",
    }
    if "electric field" in q or "điện trường" in q:
        payload["quantity"] = "field"
    return normalize_coulomb_payload(payload, question)

def extract_vector_rulebased(question: str) -> dict | None:
    question = normalize_question_text(question)
    q = question.lower()
    forces = re.findall(r"([\d.]+)\s*n\b", q)
    if len(forces) >= 2:
        f1, f2 = float(forces[0]), float(forces[1])
    elif len(forces) == 1 and ("each" in q or "both" in q or "nhau" in q):
        f1 = f2 = float(forces[0])
    else:
        return None

    if "same direction" in q or "cùng chiều" in q or "cùng hướng" in q:
        mode = "same_direction"
    elif "opposite" in q or "ngược chiều" in q or "ngược hướng" in q:
        mode = "opposite"
    elif "90" in q or "perpendicular" in q or "vuông góc" in q:
        mode = "perpendicular"
    else:
        mode = "angle"

    out = {"task_type": "vector_resultant", "mode": mode, "F1": {"value": f1, "unit": "N"}, "F2": {"value": f2, "unit": "N"}}
    ang = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|deg|độ)\b", question, re.I)
    if ang:
        out["alpha"] = {"value": float(ang.group(1)), "unit": "deg"}
    elif mode == "angle":
        return None
    return out

def extract_bisector_rulebased(question: str) -> dict | None:
    q = question.lower()
    ab_m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+apart", q) or re.search(r"cách nhau\s*([\d.]+)\s*cm", q)
    h_m = (
        re.search(r"(\d+(?:\.\d+)?)\s*cm\s+(?:away\s+from|from)\s*ab", q)
        or re.search(r"(\d+(?:\.\d+)?)\s*cm\s+from\s+each\s+charge", q)
        or re.search(r"(\d+(?:\.\d+)?)\s*cm\s+away\s+from\s+each", q)
        or re.search(r"cách đường thẳng ab\s*([\d.]+)\s*cm", q)
        or re.search(r"cách ab\s*([\d.]+)\s*cm", q)
    )
    vals = _sci_charges_from_text(question)
    if not ab_m or not h_m or len(vals) < 2:
        return None
    q_vals = vals[:2]
    q_test = vals[2] if len(vals) > 2 else 0.0
    out = {
        "task_type": "coulomb_bisector",
        "target_charge": "q3",
        "charges": {"q1": q_vals[0], "q2": q_vals[1], "q3": q_test},
        "ab_distance": float(ab_m.group(1)) * 0.01,
        "bisector_distance": float(h_m.group(1)) * 0.01,
    }
    if "electric field" in q or "điện trường" in q:
        out["quantity"] = "field"
    return out

def extract_geometry_rulebased(question: str) -> dict | None:
    return extract_labeled_triangle_rulebased(question)

def fix_llm_parsed(question: str, parsed: dict) -> dict:
    question = normalize_question_text(question)
    q = question.lower()
    task = parsed.get("task_type")

    if "electric field" in q or "điện trường" in q:
        parsed["quantity"] = "field"

    if task == "algebraic":
        knowns = parsed.get("knowns", {})
        if "V" in knowns and "U" not in knowns:
            knowns["U"] = knowns.pop("V")
            parsed["knowns"] = knowns
        if ("energy" in q or "stored" in q or "năng lượng" in q) and parsed.get("target") in ("U", "V"):
            parsed["target"] = "E"
        if ("energy" in q or "stored" in q or "năng lượng" in q) and parsed.get("target") == "U" and "C" in knowns:
            parsed["target"] = "E"
        if parsed.get("target") in ("F_resultant", "F_r", "R", "F", "F_net"):
            k = knowns
            if "F1" in k and "F2" in k and ("theta" in k or "alpha" in k):
                ang = k.get("alpha") or k.get("theta")
                return {"task_type": "vector_resultant", "mode": "angle", "F1": k["F1"], "F2": k["F2"], "alpha": ang}

    if task in ("coulomb_geometry", "coulomb_collinear"):
        fixed = _fix_charges_from_text(question, parsed.get("charges", {}))
        if fixed:
            parsed["charges"] = fixed
        rule_tri = extract_labeled_triangle_rulebased(question)
        if rule_tri:
            parsed["charges"] = rule_tri.get("charges", parsed.get("charges", {}))
            parsed["distances"] = rule_tri.get("distances", parsed.get("distances", {}))
            parsed["task_type"] = rule_tri.get("task_type", parsed.get("task_type"))
            parsed.pop("layout", None)
            if rule_tri.get("layout"):
                parsed["layout"] = rule_tri["layout"]

        dist = parsed.get("distances", {})
        if isinstance(dist, dict):
            cleaned = {}
            for k, v in dist.items():
                if v is None:
                    continue
                parts = str(k).split("_")
                if len(parts) == 2 and parts[0] != parts[1]:
                    cleaned[k] = v
            parsed["distances"] = cleaned

        if "center of" in q or "at the center" in q or "tâm" in q:
            parsed["center"] = True

        if _should_be_collinear(question, parsed):
            parsed["layout"] = "collinear"
        elif parsed.get("layout") == "collinear" and not _should_be_collinear(question, parsed):
            parsed.pop("layout", None)

        if parsed.get("triangle") == "equilateral" or _is_equilateral_question(question):
            parsed["task_type"] = "coulomb_geometry"
            parsed.pop("layout", None)

    return normalize_coulomb_payload(parsed, question)

def _fix_charges_from_text(question: str, charges: dict) -> dict:
    vals = _sci_charges_from_text(question)
    if not vals:
        return charges
    new_c = {}
    for i, (k, v) in enumerate(charges.items()):
        if i < len(vals):
            sign = -1 if v < 0 else 1
            new_c[k] = sign * abs(vals[i])
        else:
            new_c[k] = v
    return new_c

def _should_be_collinear(question: str, parsed: dict) -> bool:
    if _is_equilateral_question(question):
        return False
    if parsed.get("triangle") == "equilateral":
        return False
    q = normalize_question_text(question).lower()
    if "right-angled" in q or "right angled" in q or "isosceles right" in q or "vuông" in q:
        return False
    if parsed.get("right_angle_at"):
        return False

    edges = _parse_vertex_edges(question)
    if len(edges) >= 6:
        return False

    if "straight line" in q or "collinear" in q or "cùng một đường thẳng" in q or "thẳng hàng" in q:
        return True
    if "midpoint" in q and "segment" in q:
        return True

    dist = parsed.get("distances") or {}
    tgt = str(parsed.get("target_charge", "q3"))
    if tgt.lower() in ("q0", "qo"):
        tgt = "q0"

    links = [k for k in dist if tgt in k.split("_")]
    if len(links) >= 2:
        ab = dist.get("q1_q2") or dist.get("q2_q1")
        if not ab:
            return True
    return False

def postprocess_geometry(question: str, parsed: dict) -> dict:
    question = normalize_question_text(question)
    q = question.lower()
    if parsed.get("task_type") != "coulomb_geometry":
        return parsed

    charges = parsed.get("charges", {})
    parsed_charges = _fix_charges_from_text(question, charges)
    if parsed_charges:
        parsed["charges"] = parsed_charges

    dist = parsed.get("distances", {})
    if isinstance(dist, dict):
        edges = _parse_vertex_edges(question)
        for pair, length in [
            ("q1_q2", ("A", "B")), ("q1_q3", ("A", "C")), ("q2_q3", ("B", "C")),
            ("q1_q0", ("A", "M")), ("q2_q0", ("B", "M"))
        ]:
            if pair not in dist and pair[::-1] not in dist:
                d = _edge_len(edges, length[0], length[1])
                if d:
                    dist[pair] = d

        if "apart on a straight line" in q or "apart along a straight line" in q or "cùng một đường thẳng" in q:
            sep_m = re.search(r"([\d.]+)\s*(cm|m|mm)\s+apart", q) or re.search(r"cách nhau\s*([\d.]+)\s*(cm|m|mm)", q)
            if sep_m:
                scale = {"m": 1.0, "cm": 0.01, "mm": 0.001}
                a = float(sep_m.group(1)) * scale.get(sep_m.group(2).lower(), 1.0)
                dist["q1_q2"] = a
        parsed["distances"] = dist

    return parsed

def normalize_coulomb_payload(parsed: dict, question: str) -> dict:
    if not isinstance(parsed, dict):
        return parsed

    dist = parsed.get("distances")
    if isinstance(dist, dict):
        norm_dist = {}
        for k, v in dist.items():
            if v is None:
                continue
            try:
                if isinstance(v, str):
                    m = re.search(r"([\d.]+)\s*(cm|m|mm)?", v)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2) or "m"
                        scale = {"cm": 0.01, "m": 1.0, "mm": 0.001}
                        v = val * scale.get(unit.lower(), 1.0)
                norm_dist[str(k).lower()] = float(v)
            except (ValueError, TypeError):
                pass
        parsed["distances"] = norm_dist

    chg = parsed.get("charges")
    if isinstance(chg, dict):
        norm_chg = {}
        for k, v in chg.items():
            if v is None:
                continue
            try:
                if isinstance(v, str):
                    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(uc|mc|nc|pc|c)?", v, re.I)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2) or "c"
                        scale = {"uc": 1e-6, "mc": 1e-3, "nc": 1e-9, "pc": 1e-12, "c": 1.0}
                        v = val * scale.get(unit.lower(), 1.0)
                norm_chg[str(k).lower()] = float(v)
            except (ValueError, TypeError):
                pass
        parsed["charges"] = norm_chg

    return parsed

def _attach_question(parsed: dict, question: str) -> dict:
    if isinstance(parsed, dict) and "error" not in parsed:
        parsed["_question"] = question
    return parsed
