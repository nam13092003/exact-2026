from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.formatter import normalize_answer, parse_float_like
from agents.pipeline import ExactPipeline


def unit_norm(u: Any) -> str:
    u = str(u or "").strip().lower()
    u = u.replace("µ", "μ")

    aliases = {
        "degree": "độ",
        "degrees": "độ",
        "ohms": "ω",
        "ohm": "ω",
        "newton": "n",
        "newtons": "n",
        "volt": "v",
        "volts": "v",
        "watt": "w",
        "watts": "w",
        "joule": "j",
        "joules": "j",
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
        "second": "s",
        "seconds": "s",
    }

    return aliases.get(u, u)


def answer_match(
    pred: Any,
    gold: Any,
    pred_unit: Any = "",
    gold_unit: Any = "",
    numeric_tol: float = 1e-2,
) -> bool:
    pg = normalize_answer(pred)
    gg = normalize_answer(gold)

    if pg == gg:
        return not gold_unit or unit_norm(pred_unit) == unit_norm(gold_unit)

    pv = parse_float_like(pred)
    gv = parse_float_like(gold)

    if pv is not None and gv is not None:
        tol = max(numeric_tol, abs(gv) * 1e-3)
        return abs(pv - gv) <= tol and (
            not gold_unit or unit_norm(pred_unit) == unit_norm(gold_unit)
        )

    return False


def _safe_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def eval_logic(
    path: str,
    pipe: ExactPipeline,
    max_records: Optional[int] = None,
    use_fol: bool = True,
) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if max_records:
        data = data[:max_records]

    total = 0
    correct = 0
    rag_used_count = 0
    rag_fol_used_count = 0
    rows = []

    from tqdm import tqdm
    for ridx, rec in enumerate(tqdm(data, desc="Evaluating Logic")):
        questions = _safe_list(rec.get("questions"))
        answers = _safe_list(rec.get("answers"))

        for qidx, q in enumerate(questions):
            payload = {
                "type": "logic",
                "question": q,
                "premises-NL": rec.get("premises-NL", []),
                "idx": rec.get("idx"),
                "__record_index": ridx,
                "__question_index": qidx,
            }

            if use_fol:
                payload["premises-FOL"] = rec.get("premises-FOL", [])

            pred = pipe.predict(payload)

            gold = answers[qidx] if qidx < len(answers) else None
            ok = answer_match(pred.get("answer"), gold)

            total += 1
            correct += int(ok)

            rag_used = bool(pred.get("rag_used"))
            rag_fol_used = bool(pred.get("rag_fol_used"))

            rag_used_count += int(rag_used)
            rag_fol_used_count += int(rag_fol_used)

            rows.append(
                {
                    "task": "logic",
                    "record": ridx,
                    "idx": rec.get("idx"),
                    "question_index": qidx,
                    "question": q,
                    "pred": pred.get("answer"),
                    "gold": gold,
                    "ok": ok,
                    "confidence": pred.get("confidence"),
                    "question_type": pred.get("question_type"),
                    "rag_used": rag_used,
                    "rag_fol_used": rag_fol_used,
                    "rag_context": pred.get("rag_context", [])[:3],
                    "cot": pred.get("cot", [])[:5],
                    "fol": pred.get("fol"),
                }
            )

    return {
        "task": "logic",
        "total": total,
        "correct": correct,
        "p1": correct / total if total else 0.0,
        "rag_used_count": rag_used_count,
        "rag_used_rate": rag_used_count / total if total else 0.0,
        "rag_fol_used_count": rag_fol_used_count,
        "rag_fol_used_rate": rag_fol_used_count / total if total else 0.0,
        "rows": rows,
    }


def eval_physics(
    path: str,
    pipe: ExactPipeline,
    max_records: Optional[int] = None,
) -> Dict[str, Any]:
    raw_data = json.loads(Path(path).read_text(encoding="utf-8"))

    # Bỏ các record QA nếu dataset có.
    data = [
        r
        for r in raw_data
        if not str(r.get("id", "")).startswith("QA")
    ]

    if max_records:
        data = data[:max_records]

    total = 0
    correct = 0
    rag_used_count = 0
    rows = []

    for ridx, rec in enumerate(data):
        payload = {
            "type": "physics",
            "id": rec.get("id"),
            "question": rec.get("question", ""),
            "__record_index": ridx,
        }

        pred = pipe.predict(payload)

        ok = answer_match(
            pred.get("answer"),
            rec.get("answer"),
            pred.get("unit"),
            rec.get("unit"),
        )

        total += 1
        correct += int(ok)

        rag_used = bool(pred.get("rag_used"))
        rag_used_count += int(rag_used)

        rows.append(
            {
                "task": "physics",
                "record": ridx,
                "id": rec.get("id"),
                "question": rec.get("question", ""),
                "pred": pred.get("answer"),
                "pred_unit": pred.get("unit"),
                "gold": rec.get("answer"),
                "gold_unit": rec.get("unit"),
                "ok": ok,
                "confidence": pred.get("confidence"),
                "rag_used": rag_used,
                "rag_context": pred.get("rag_context", [])[:3],
                "cot": pred.get("cot", [])[:5],
            }
        )

    return {
        "task": "physics",
        "total": total,
        "correct": correct,
        "p1": correct / total if total else 0.0,
        "rag_used_count": rag_used_count,
        "rag_used_rate": rag_used_count / total if total else 0.0,
        "rows": rows,
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = sum(r["total"] for r in results)
    correct = sum(r["correct"] for r in results)

    rag_used_count = sum(r.get("rag_used_count", 0) for r in results)
    rag_fol_used_count = sum(r.get("rag_fol_used_count", 0) for r in results)

    by_task = [
        {
            k: v
            for k, v in r.items()
            if k != "rows"
        }
        for r in results
    ]

    return {
        "total": total,
        "correct": correct,
        "p1": correct / total if total else 0.0,
        "rag_used_count": rag_used_count,
        "rag_used_rate": rag_used_count / total if total else 0.0,
        "rag_fol_used_count": rag_fol_used_count,
        "rag_fol_used_rate": rag_fol_used_count / total if total else 0.0,
        "by_task": by_task,
    }