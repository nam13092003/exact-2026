from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _tokens(text: str) -> List[str]:
    stop = {"a","an","the","is","are","to","of","and","or","if","then","all","every","does","do","did","it","that","according","premises","with","in","on","for","be","by","from"}
    return [w for w in re.findall(r"[a-zA-Z0-9_]+", (text or "").lower()) if len(w) > 1 and w not in stop]


def _join_record(rec: Dict[str, Any]) -> str:
    parts: List[str] = []
    parts.extend(map(str, rec.get("premises-NL", [])))
    parts.extend(map(str, rec.get("questions", [])))
    return "\n".join(parts)


class LogicRAGRetriever:
    """Small dependency-free BM25 retriever over the provided logic dataset.

    It retrieves examples containing NL premises, FOL premises, questions, answers,
    and explanations. For exact/near-exact premise matches, the FOL can be reused as
    a strong symbolic representation; otherwise it is used only as a pattern hint.
    """

    def __init__(self, dataset_path: Optional[str] = None, top_k: int = 3):
        self.dataset_path = str(dataset_path) if dataset_path else ""
        self.top_k = top_k
        self.records: List[Dict[str, Any]] = []
        self.doc_tokens: List[List[str]] = []
        self.df: Counter[str] = Counter()
        self.avgdl = 1.0
        if dataset_path and Path(dataset_path).exists():
            self.load(dataset_path)

    @property
    def enabled(self) -> bool:
        return bool(self.records)

    def load(self, dataset_path: str) -> None:
        data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        self.records = [r for r in data if isinstance(r, dict)]
        self.doc_tokens = [_tokens(_join_record(r)) for r in self.records]
        self.df = Counter()
        for toks in self.doc_tokens:
            self.df.update(set(toks))
        self.avgdl = sum(len(t) for t in self.doc_tokens) / max(1, len(self.doc_tokens))

    def _bm25(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        tf = Counter(doc_tokens)
        n = max(1, len(self.doc_tokens))
        k1, b = 1.5, 0.75
        score = 0.0
        dl = len(doc_tokens)
        for term in query_tokens:
            df = self.df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            freq = tf.get(term, 0)
            denom = freq + k1 * (1 - b + b * dl / self.avgdl)
            score += idf * (freq * (k1 + 1)) / max(1e-9, denom)
        return score

    def retrieve(
        self,
        question: str,
        premises_nl: List[str],
        top_k: Optional[int] = None,
        exclude_record_index: Optional[int] = None,
        exclude_idx: Optional[Any] = None,
        exclude_question: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        query = "\n".join(list(premises_nl or []) + [question or ""])
        q_tokens = _tokens(query)
        scored: List[Tuple[float, int]] = []
        premise_set = {p.strip().lower() for p in premises_nl or []}
        exclude_idx_s = str(exclude_idx) if exclude_idx is not None else None
        exclude_q_norm = re.sub(r"\s+", " ", str(exclude_question or "").strip().lower())
        for i, toks in enumerate(self.doc_tokens):
            rec = self.records[i]
            if exclude_record_index is not None and i == int(exclude_record_index):
                continue
            if exclude_idx_s is not None and str(rec.get("idx", "")) == exclude_idx_s:
                continue
            # Avoid exact duplicate question leakage as well as the same row.
            if exclude_q_norm:
                rec_questions = [re.sub(r"\s+", " ", str(q or "").strip().lower()) for q in rec.get("questions", [])]
                if exclude_q_norm in rec_questions:
                    continue
            score = self._bm25(q_tokens, toks)
            rec_premise_set = {str(p).strip().lower() for p in rec.get("premises-NL", [])}
            if premise_set and premise_set == rec_premise_set:
                score += 50.0
            scored.append((score, i))
        scored.sort(reverse=True)
        out = []
        for score, i in scored[: top_k or self.top_k]:
            r = self.records[i]
            out.append({
                "score": round(score, 4),
                "record_index": i,
                "premises-NL": r.get("premises-NL", []),
                "premises-FOL": r.get("premises-FOL", []),
                "questions": r.get("questions", []),
                "answers": r.get("answers", []),
                "explanation": r.get("explanation", []),
            })
        return out

    def best_fol_if_same_premises(self, premises_nl: List[str], retrieved: List[Dict[str, Any]]) -> Optional[List[str]]:
        premise_set = {p.strip().lower() for p in premises_nl or []}
        if not premise_set:
            return None
        for r in retrieved:
            rec_set = {str(p).strip().lower() for p in r.get("premises-NL", [])}
            fol = r.get("premises-FOL") or []
            if fol and rec_set == premise_set:
                return list(map(str, fol))
        return None
