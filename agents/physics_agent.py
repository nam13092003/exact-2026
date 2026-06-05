from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agents.formatter import extract_json, standard_response
from agents.llm_client import VLLMClient
from agents.physics_rag import PhysicsRAGRetriever
from tools.calculator import solve_by_formula


class PhysicsAgent:
    """Physics pipeline: leakage-safe RAG few-shot -> formula tool -> local LLM -> optional RAG fallback.

    RAG is always attempted when use_rag=True and the KB is loaded.
    Retrieved examples are primarily used as few-shot guidance for formula choice,
    reasoning style, and unit format.
    """

    def __init__(self, kb_path: Optional[str] = None, llm: Optional[VLLMClient] = None):
        self.llm = llm or VLLMClient()
        self.rag = PhysicsRAGRetriever(kb_path) if kb_path else PhysicsRAGRetriever(None)

    def _format_rag_context(self, retrieved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "record_index": r.get("record_index"),
                "id": r.get("id"),
                "score": r.get("score"),
                "question": r.get("question", "")[:180],
                "answer": r.get("answer", ""),
                "unit": r.get("unit", ""),
            }
            for r in retrieved
        ]

    def _build_fewshot_payload(
        self,
        fewshot_examples: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        fewshots: List[Dict[str, Any]] = []

        for ex in (fewshot_examples or [])[:3]:
            cot = ex.get("cot", "")

            if isinstance(cot, list):
                cot_text = "\n".join(map(str, cot))
            else:
                cot_text = str(cot or "")

            fewshots.append(
                {
                    "similar_record_index": ex.get("record_index"),
                    "similar_id": ex.get("id"),
                    "similar_score": ex.get("score"),
                    "similar_question": ex.get("question", ""),
                    "similar_answer": ex.get("answer", ""),
                    "similar_unit": ex.get("unit", ""),
                    "similar_solution_steps": cot_text[:1200],
                }
            )

        return fewshots

    def solve_with_llm(
        self,
        question: str,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.llm.enabled:
            return None

        system = (
            "Solve the physics problem using explicit steps and calculator-style formulas. "
            "Return JSON only with this schema: "
            "{answer: string, unit: string, cot: [steps], premises: [formulas], confidence: number}. "
            "Use concise final numeric answer. "
            "Retrieved examples are FEW-SHOT GUIDANCE ONLY. Do not copy their final answer unless the current problem has the same quantities and asks the same thing. "
            "Use retrieved examples only to identify the likely formula, reasoning style, and unit format. "
            "Always solve only the current_question."
        )

        user_payload = {
            "fewshot_examples": self._build_fewshot_payload(fewshot_examples),
            "current_question": question,
            "instruction": (
                "Solve only current_question. "
                "Use fewshot_examples only as formula/style guidance. "
                "Show the formula in premises and concise calculation steps in cot."
            ),
        }

        try:
            text = self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            obj = extract_json(text)

            if obj and obj.get("answer"):
                return obj

        except Exception:
            return None

        return None

    def solve(
        self,
        question: str,
        exclude_id: Optional[str] = None,
        exclude_record_index: Optional[int] = None,
        use_rag: bool = True,
    ) -> Dict[str, Any]:
        # Stage 0: always attempt leakage-safe RAG when enabled.
        rag_attempted = bool(use_rag and self.rag.enabled)

        retrieved = self.rag.retrieve(
            question,
            top_k=5,
            exclude_id=exclude_id,
            exclude_record_index=exclude_record_index,
            exclude_question=question,
        ) if rag_attempted else []

        rag_context = self._format_rag_context(retrieved)
        rag_used = bool(retrieved)

        # Stage 1: deterministic formula solver.
        calc = solve_by_formula(question)

        if calc:
            cot = list(calc.cot or [])

            if rag_used:
                cot.append("RAG retrieved similar solved physics examples as few-shot references.")
            elif rag_attempted:
                cot.append("RAG was attempted, but no similar physics example was retrieved.")

            return standard_response(
                calc.answer,
                (
                    "The calculator tool matched a physics formula pattern and computed the result step by step. "
                    "RAG retrieval was attempted first and any retrieved examples were used only as few-shot references."
                ),
                unit=calc.unit,
                cot=cot,
                premises=["symbolic calculator", "physics formula library"],
                confidence=calc.confidence,
                rag_attempted=rag_attempted,
                rag_used=rag_used,
                rag_context=rag_context,
            )

        # Stage 2: LLM solver with RAG few-shot examples.
        llm_obj = self.solve_with_llm(question, fewshot_examples=retrieved)

        if llm_obj:
            ans = llm_obj.get("answer", "Unknown")
            unit = llm_obj.get("unit", "")
            cot = llm_obj.get("cot", [])

            if isinstance(cot, str):
                cot = [cot]
            else:
                cot = list(cot or [])

            if rag_used:
                cot.append("RAG retrieved similar examples and injected them as few-shot solver guidance.")
            elif rag_attempted:
                cot.append("RAG was attempted, but no similar physics example was retrieved.")

            return standard_response(
                ans,
                (
                    "A local open-source LLM produced a structured solution. "
                    "RAG retrieval was attempted first and retrieved examples were used only as few-shot formula/style guidance."
                ),
                unit=unit,
                cot=cot,
                premises=llm_obj.get("premises"),
                confidence=llm_obj.get("confidence", 0.65),
                rag_attempted=rag_attempted,
                rag_used=rag_used,
                rag_context=rag_context,
            )

        # Stage 3: optional conservative RAG fallback.
        # Giữ đoạn này nếu bạn muốn khi calculator/LLM fail thì lấy mẫu gần nhất.
        # Nếu bạn muốn RAG CHỈ làm few-shot, hãy thay Stage 3 bằng return Unknown.
        if retrieved and retrieved[0].get("score", 0) >= 8.0:
            ex = retrieved[0]
            cot = ex.get("cot", "")
            cot_list = cot.split("\n") if isinstance(cot, str) else list(cot or [])

            return standard_response(
                ex.get("answer", "Unknown"),
                (
                    "Formula solver and local LLM failed. "
                    f"The leakage-safe physics RAG fallback used the nearest different solved problem ({ex.get('id')}) "
                    f"with BM25 score {ex.get('score')}. "
                    "This fallback is lower-confidence than direct solving."
                ),
                unit=ex.get("unit", ""),
                cot=cot_list[:8],
                premises=[
                    f"retrieved_example_id={ex.get('id')}",
                    f"bm25_score={ex.get('score')}",
                    "fallback_mode=nearest_different_example",
                ],
                confidence=0.62,
                rag_attempted=rag_attempted,
                rag_used=True,
                rag_context=rag_context,
            )

        return standard_response(
            "Unknown",
            (
                "No formula pattern matched, no local LLM endpoint produced a solution, "
                "and leakage-safe RAG similarity was too low for a reliable fallback answer."
            ),
            unit="",
            cot=[
                "Route=physics",
                "RAG excludes the current test item",
                "Formula solver failed",
                "LLM disabled or failed",
                "RAG fallback below threshold",
            ],
            confidence=0.15,
            rag_attempted=rag_attempted,
            rag_used=rag_used,
            rag_context=rag_context,
        )