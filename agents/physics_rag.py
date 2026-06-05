from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _tokens(text: str) -> List[str]:
    stop = {
        "a", "an", "the", "is", "are", "to", "of", "and", "or", "if", "then", "all", "every",
        "does", "do", "did", "it", "that", "according", "with", "in", "on", "for", "be", "by", "from",
        "calculate", "determine", "find", "given", "what", "when", "under", "problem"
    }
    return [w for w in re.findall(r"[a-zA-Z0-9_µμΩ.\-^]+", (text or "").lower()) if len(w) > 1 and w not in stop]


class PhysicsRAGRetriever:
    """Dependency-free BM25 retriever for solved physics examples.

    Evaluation safety: `retrieve` accepts `exclude_id`, `exclude_record_index`, and
    `exclude_question`. The current test example is skipped before ranking, so RAG
    cannot simply copy its own gold answer.
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

    @staticmethod
    def _norm_question(s: Any) -> str:
        return re.sub(r"\s+", " ", str(s or "").strip().lower())

    def load(self, dataset_path: str) -> None:
        data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        self.records = [r for r in data if isinstance(r, dict) and not str(r.get("id", "")).startswith("QA")]
        self.doc_tokens = [_tokens("\n".join([str(r.get("question", "")), str(r.get("cot", "")), str(r.get("unit", ""))])) for r in self.records]
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
        top_k: Optional[int] = None,
        exclude_id: Optional[str] = None,
        exclude_record_index: Optional[int] = None,
        exclude_question: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        q_tokens = _tokens(question or "")
        exclude_id_s = str(exclude_id) if exclude_id is not None else None
        exclude_q_norm = self._norm_question(exclude_question) if exclude_question else ""
        scored: List[Tuple[float, int]] = []
        for i, toks in enumerate(self.doc_tokens):
            rec = self.records[i]
            if exclude_record_index is not None and i == int(exclude_record_index):
                continue
            if exclude_id_s and str(rec.get("id", "")) == exclude_id_s:
                continue
            # Also avoid exact duplicate text leakage when a duplicated row exists.
            if exclude_q_norm and self._norm_question(rec.get("question", "")) == exclude_q_norm:
                continue
            score = self._bm25(q_tokens, toks)
            scored.append((score, i))
        scored.sort(reverse=True)
        out: List[Dict[str, Any]] = []
        for score, i in scored[: top_k or self.top_k]:
            r = self.records[i]
            out.append({
                "score": round(score, 4),
                "record_index": i,
                "id": r.get("id"),
                "question": r.get("question", ""),
                "answer": r.get("answer", "Unknown"),
                "unit": r.get("unit", ""),
                "cot": r.get("cot", ""),
            })
        return out
