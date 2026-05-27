from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agents.formatter import normalize_answer, parse_float_like
from agents.pipeline import ExactPipeline


def unit_norm(u: Any) -> str:
    u = str(u or "").strip().lower()
    # Unescape double-escaped unicode sequences like '\\u0110\\u1ed9' using regex decode
    def _unescape_unicode(s: str) -> str:
        return re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda m: chr(int(m.group(1), 16)),
            s,
        )
    u = _unescape_unicode(u)
    # Also handle literal escape sequences
    u = u.replace("\\u03bc", "μ").replace("\\u00b0", "độ").replace("\\u2126", "ω")
    # Normalize Greek/Latin micro to 'u'
    u = u.replace("μ", "u").replace("µ", "u")
    aliases = {
        "degree": "độ", "degrees": "độ", "deg": "độ", "°": "độ",
        "ohms": "ω", "ohm": "ω", "w": "ω", "omega": "ω",
        "v/m": "v/m", "v": "v", "a": "a", "hz": "hz",
        "fa": "f", "f": "f", "uf": "uf", "pf": "pf", "nf": "nf", "mf": "mf",
    }
    return aliases.get(u, u)


def to_si(value: float, unit: str) -> Tuple[float, str]:
    u = unit_norm(unit)
    
    # Prefix scales
    prefix_scales = {
        "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        "k": 1e3,
    }
    
    # Identify base unit and prefix
    # Distinguish between milli and Mega: if base unit is hz, 'm' prefix is Mega (1e6)
    for base in ("hz", "v/m", "m2", "m", "f", "c", "j", "v", "h", "a", "n", "độ", "ω"):
        if u.endswith(base):
            prefix = u[:-len(base)]
            scale = 1.0
            if prefix:
                if base == "hz" and prefix == "m":
                    scale = 1e6  # MegaHz
                elif prefix in prefix_scales:
                    scale = prefix_scales[prefix]
            return value * scale, base
            
    return value, u


def answer_match(pred: Any, gold: Any, pred_unit: Any = "", gold_unit: Any = "", numeric_tol: float = 1e-2) -> bool:
    pg = normalize_answer(pred)
    gg = normalize_answer(gold)
    
    # Case-insensitive match on normalized strings
    if pg == gg:
        # Check normalized units if gold unit is present
        if not gold_unit:
            return True
        return unit_norm(pred_unit) == unit_norm(gold_unit)
        
    # Attempt numeric/physics-aware comparison
    pv, gv = parse_float_like(pred), parse_float_like(gold)
    if pv is not None and gv is not None:
        if gold_unit:
            # Physics-aware comparison
            p_si_val, p_si_unit = to_si(pv, pred_unit)
            g_si_val, g_si_unit = to_si(gv, gold_unit)
            if p_si_unit == g_si_unit:
                tol = max(numeric_tol, abs(g_si_val) * 1e-3)
                return abs(p_si_val - g_si_val) <= tol
        else:
            # No unit expected, pure numeric check
            tol = max(numeric_tol, abs(gv) * 1e-3)
            return abs(pv - gv) <= tol
            
    return False


def eval_logic(path: str, pipe: ExactPipeline, max_records: Optional[int] = None, use_fol: bool = True) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    total = correct = 0
    rows = []
    for ridx, rec in enumerate(data[:max_records] if max_records else data):
        for qidx, q in enumerate(rec.get("questions", [])):
            payload = {
                "type": "logic",
                "question": q,
                "premises-NL": rec.get("premises-NL", []),
            }
            if use_fol:
                payload["premises-FOL"] = rec.get("premises-FOL", [])
            pred = pipe.predict(payload)
            gold = rec.get("answers", [None])[qidx]
            ok = answer_match(pred.get("answer"), gold)
            total += 1
            correct += int(ok)
            rows.append({"record": ridx, "question_index": qidx, "pred": pred.get("answer"), "gold": gold, "ok": ok})
    return {"task": "logic", "total": total, "correct": correct, "p1": correct / total if total else 0.0, "rows": rows}


def eval_physics(path: str, pipe: ExactPipeline, max_records: Optional[int] = None) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data = [r for r in data if not str(r.get("id", "")).startswith("QA")]
    total = correct = 0
    rows = []
    for ridx, rec in enumerate(data[:max_records] if max_records else data):
        payload = {"type": "physics", "id": rec.get("id"), "question": rec.get("question", "")}
        pred = pipe.predict(payload)
        ok = answer_match(pred.get("answer"), rec.get("answer"), pred.get("unit"), rec.get("unit"))
        total += 1
        correct += int(ok)
        rows.append({"record": ridx, "id": rec.get("id"), "pred": pred.get("answer"), "pred_unit": pred.get("unit"), "gold": rec.get("answer"), "gold_unit": rec.get("unit"), "ok": ok})
    return {"task": "physics", "total": total, "correct": correct, "p1": correct / total if total else 0.0, "rows": rows}


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = sum(r["total"] for r in results)
    correct = sum(r["correct"] for r in results)
    return {"total": total, "correct": correct, "p1": correct / total if total else 0.0, "by_task": [{k: v for k, v in r.items() if k != "rows"} for r in results]}
