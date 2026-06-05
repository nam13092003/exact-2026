from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.formatter import extract_json, standard_response
from agents.llm_client import VLLMClient
from agents.logic_question_classifier import classify_logic_question, prompt_for_type
from agents.logic_rag import LogicRAGRetriever
from tools.z3_logic import Atom, HornKB, Rule, parse_fol_to_kb, pred_name


def split_choices(question: str) -> Dict[str, str]:
    choices: Dict[str, str] = {}
    matches = list(re.finditer(r"(?:^|\n)\s*([A-D])\.\s*", question))

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(question)
        choices[m.group(1)] = question[start:end].strip()

    return choices


def question_stem(question: str) -> str:
    return re.split(r"\n\s*A\.\s*", question)[0].strip()


def tokenize(s: str) -> set:
    stop = {
        "a", "an", "the", "is", "are", "be", "to", "for", "of", "with",
        "and", "or", "if", "then", "all", "every", "does", "do", "did",
        "can", "could", "should", "must", "based", "premises", "according",
        "about", "on", "in", "that", "it", "he", "she", "they",
        "student", "students", "project", "projects", "system", "systems",
        "faculty", "member", "members",
    }

    return {
        w
        for w in re.findall(r"[a-zA-Z0-9_]+", s.lower())
        if w not in stop and len(w) > 1
    }


def atom_words(atom: Atom) -> set:
    return tokenize(atom.pred.replace("_", " ") + " " + " ".join(atom.args))


class LogicNLParserAgent:
    """Convert natural language premises/questions to compact Horn-logic JSON.

    RAG examples are injected as few-shot guidance only. They guide the parser on
    representation style, but they must not be used as direct answer sources.
    """

    def __init__(self, llm: Optional[VLLMClient] = None):
        self.llm = llm or VLLMClient()

    def _build_fewshot_payload(
        self,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        fewshots: List[Dict[str, Any]] = []

        for ex in (fewshot_examples or [])[:3]:
            fewshots.append(
                {
                    "similar_record_index": ex.get("record_index"),
                    "similar_score": ex.get("score"),
                    "similar_premises_nl": ex.get("premises-NL", [])[:8],
                    "similar_premises_fol": ex.get("premises-FOL", [])[:12],
                    "similar_questions": ex.get("questions", [])[:2],
                    "similar_answers": ex.get("answers", [])[:2],
                    "similar_explanation": ex.get("explanation", [])[:2],
                }
            )

        return fewshots

    def parse_with_llm(
        self,
        premises_nl: List[str],
        question: str,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.llm.enabled:
            return None

        system = (
            "You convert educational rules into a finite Horn-logic JSON for Z3. "
            "Return JSON only. Predicates must be snake_case. Use concrete constants when named entities appear. "
            "Schema: {facts:[{pred,args,truth,source}], rules:[{if:[{pred,args,truth}], then:{pred,args,truth}, source}], "
            "query:{pred,args,truth}|null, choices:{A:{pred,args,truth},...}|{}}. "
            "Use args ['entity'] for generic universal claims if no named entity is present. "
            "Retrieved examples are FEW-SHOT GUIDANCE ONLY. Do not copy their final answers. "
            "Use retrieved examples only to imitate how natural-language premises are converted into facts, rules, query, and choices. "
            "Always solve only current_task."
        )

        user_payload = {
            "fewshot_examples": self._build_fewshot_payload(fewshot_examples),
            "current_task": {
                "premises": premises_nl,
                "question": question,
            },
            "instruction": (
                "Convert only current_task into the required Horn-logic JSON. "
                "If the current question has A-D options, formalize every option in choices. "
                "Do not copy the answer from retrieved examples."
            ),
        }

        try:
            text = self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            return extract_json(text)
        except Exception:
            return None

    def fallback_parse_premises(self, premises_nl: List[str]) -> HornKB:
        kb = HornKB()

        for i, p in enumerate(premises_nl, 1):
            src = f"Premise {i}: {p}"
            s = p.strip().rstrip(".")

            # If A then B.
            m = re.match(r"if\s+(.+?),?\s+then\s+(.+)$", s, flags=re.I)
            if not m:
                m = re.match(r"(.+?)\s+implies\s+(.+)$", s, flags=re.I)

            if m:
                ant_str = m.group(1)
                cons_str = m.group(2)
                
                ants = []
                for a in re.split(r"\s+and\s+", ant_str, flags=re.I):
                    truth = True
                    if re.search(r"\b(not|cannot)\b", a, flags=re.I):
                        truth = False
                    
                    em = re.match(r"(?:a\s+|an\s+|the\s+|every\s+|all\s+)?([a-z0-9_]+)\s+(.+)", a.strip(), flags=re.I)
                    if em:
                        pred = pred_name(em.group(2).replace("not ", "").replace("cannot ", "can "))
                    else:
                        pred = pred_name(a.replace("not ", "").replace("cannot ", "can "))
                    ants.append(Atom(pred, ("entity",), truth))

                cons_truth = True
                if re.search(r"\b(not|cannot)\b", cons_str, flags=re.I):
                    cons_truth = False
                
                cem = re.match(r"(?:a\s+|an\s+|the\s+|every\s+|all\s+)?([a-z0-9_]+)\s+(.+)", cons_str.strip(), flags=re.I)
                if cem:
                    c_pred = pred_name(cem.group(2).replace("not ", "").replace("cannot ", "can "))
                else:
                    c_pred = pred_name(cons_str.replace("not ", "").replace("cannot ", "can "))
                
                kb.add_rule(Rule(ants, Atom(c_pred, ("entity",), cons_truth), src))
                continue

            # All X are Y / Every X is Y.
            m = re.match(r"(?:all|every)\s+(.+?)\s+(?:are|is)\s+(.+)$", s, flags=re.I)
            if m:
                ant = pred_name(m.group(1))
                cons = pred_name(m.group(2))
                kb.add_rule(
                    Rule(
                        [Atom(ant, ("entity",), True)],
                        Atom(cons, ("entity",), True),
                        src,
                    )
                )
                kb.add_fact(Atom(ant, ("entity",), True), src)
                continue

            # Named fact: Sophia has completed ... / John maintains ...
            m = re.match(r"(?:professor\s+|dr\.\s+)?([A-Z][A-Za-z0-9_]+)\s+(.+)$", s)
            if m:
                truth = True
                if re.search(r"\b(not|cannot)\b", m.group(2), flags=re.I):
                    truth = False

                name = pred_name(m.group(1))
                phrase = pred_name(m.group(2).replace("not ", "").replace("cannot ", "can "))
                phrase = re.sub(
                    r"^(has|have|is|are|maintains|completed|received)_",
                    "",
                    phrase,
                )
                kb.add_fact(Atom(phrase, (name,), truth), src)

        kb.closure()
        return kb

    def fallback_parse_query(self, question: str) -> Optional[Atom]:
        q = question.strip().rstrip("?!.").lower()
        m = re.match(r"^(?:can|could|does|did|is|are|will|would|should|has|have)\s+(?:a\s+|an\s+|the\s+)?([a-z0-9_]+(?:_[a-z0-9_]+)*)\s+(.+)$", q)
        if m:
            entity = pred_name(m.group(1))
            phrase = pred_name(m.group(2))
            phrase = re.sub(r"^(be|been|have|has)_", "", phrase)
            return Atom(phrase, (entity,), True)
        return None

    def build_kb(
        self,
        premises_nl: List[str],
        question: str,
        premises_fol: Optional[List[str]] = None,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[HornKB, Optional[Dict[str, Any]]]:
        parsed = self.parse_with_llm(
            premises_nl,
            question,
            fewshot_examples=fewshot_examples,
        )

        if parsed:
            kb = HornKB()

            for f in parsed.get("facts", []):
                kb.add_fact(
                    Atom(
                        pred_name(f.get("pred", "predicate")),
                        tuple(map(pred_name, f.get("args", ["entity"]))),
                        bool(f.get("truth", True)),
                    ),
                    f.get("source", "LLM fact"),
                )

            for r in parsed.get("rules", []):
                ants = [
                    Atom(
                        pred_name(a.get("pred", "predicate")),
                        tuple(map(pred_name, a.get("args", ["entity"]))),
                        bool(a.get("truth", True)),
                    )
                    for a in r.get("if", [])
                ]

                th = r.get("then", {})

                if ants and th:
                    kb.add_rule(
                        Rule(
                            ants,
                            Atom(
                                pred_name(th.get("pred", "predicate")),
                                tuple(map(pred_name, th.get("args", ["entity"]))),
                                bool(th.get("truth", True)),
                            ),
                            r.get("source", "LLM rule"),
                        )
                    )

            kb.closure()
            return kb, parsed

        if premises_fol:
            return parse_fol_to_kb(premises_fol), None

        return self.fallback_parse_premises(premises_nl), None


def json_atom_to_atom(obj: Any) -> Optional[Atom]:
    if not isinstance(obj, dict) or not obj.get("pred"):
        return None

    return Atom(
        pred_name(obj.get("pred")),
        tuple(map(pred_name, obj.get("args", ["entity"]))),
        bool(obj.get("truth", True)),
    )


class Z3ReasonerAgent:
    def answer_atom(self, kb: HornKB, atom: Atom) -> str:
        ent = kb.entails(atom)

        if ent is True:
            return "Yes"
        if ent is False:
            return "No"

        return "Unknown"

    def best_choice(
        self,
        kb: HornKB,
        question: str,
        parsed: Optional[Dict[str, Any]],
    ) -> Tuple[str, Optional[Atom], float]:
        choices = split_choices(question)

        if not choices:
            return "Unknown", None, 0.25

        # Preferred: LLM provided formal choices.
        if parsed and isinstance(parsed.get("choices"), dict):
            for label, obj in parsed["choices"].items():
                atom = json_atom_to_atom(obj)

                if atom and kb.entails(atom) is True:
                    return label, atom, 0.85

        # Fallback: pick option whose text overlaps derived atoms the most.
        kb.closure()
        positive_atoms = [a for a in kb.facts if a.truth]
        best = ("Unknown", None, 0.0)

        for label, text in choices.items():
            tw = tokenize(text)
            score = 0.0
            best_atom = None

            for atom in positive_atoms:
                aw = atom_words(atom)

                if not aw:
                    continue

                overlap = len(tw & aw) / max(1, len(tw | aw))

                if overlap > score:
                    score, best_atom = overlap, atom

            # Penalize option words that indicate need/cannot/not when no negation exists.
            if re.search(r"\b(needs?|cannot|not|insufficient|lacks?)\b", text, flags=re.I):
                if best_atom and best_atom.truth:
                    score *= 0.65

            if score > best[2]:
                best = (label, best_atom, score)

        if best[2] >= 0.08:
            return best[0], best[1], min(0.65, 0.35 + best[2])

        return "Unknown", None, 0.25

    def yes_no_unknown(
        self,
        kb: HornKB,
        question: str,
        parsed: Optional[Dict[str, Any]],
        fallback_query_atom: Optional[Atom] = None,
    ) -> Tuple[str, Optional[Atom], float]:
        if parsed:
            atom = json_atom_to_atom(parsed.get("query"))

            if atom:
                return self.answer_atom(kb, atom), atom, 0.85

        if fallback_query_atom:
            kb_preds = set()
            for f in kb.facts: kb_preds.add(f.pred)
            for r in kb.rules: 
                kb_preds.add(r.consequent.pred)
                for a in r.antecedents: kb_preds.add(a.pred)
                
            best_pred = fallback_query_atom.pred
            best_score = 0.0
            tw = tokenize(best_pred.replace("_", " "))
            
            for kp in kb_preds:
                kw = tokenize(kp.replace("_", " "))
                if kw and tw:
                    overlap = len(tw & kw) / max(1, len(tw | kw))
                    if overlap > best_score and overlap > 0.3:
                        best_score = overlap
                        best_pred = kp
                        
            aligned_atom = Atom(best_pred, fallback_query_atom.args, fallback_query_atom.truth)
            ent = kb.entails(aligned_atom)
            if ent is True:
                return "Yes", aligned_atom, 0.85
            if ent is False:
                return "No", aligned_atom, 0.85

        # Fallback: match question words to known positive/negative facts.
        qw = tokenize(question)
        kb.closure()

        best_atom = None
        best_score = 0.0

        for atom in kb.facts:
            aw = atom_words(atom)
            score = len(qw & aw) / max(1, len(qw | aw))

            if score > best_score:
                best_score = score
                best_atom = atom

        if best_atom and best_score >= 0.10:
            return (
                "Yes" if best_atom.truth else "No",
                best_atom,
                min(0.7, 0.35 + best_score),
            )

        return "Unknown", None, 0.25


class ExplanationAgent:
    def __init__(self, llm: Optional[VLLMClient] = None):
        self.llm = llm or VLLMClient()

    def explain(
        self,
        question: str,
        answer: str,
        atom: Optional[Atom],
        kb: HornKB,
        premises_nl: List[str],
        cot: List[str],
    ) -> str:
        if self.llm.enabled:
            try:
                prompt = {
                    "question": question,
                    "answer": answer,
                    "entailed_atom": atom.label() if atom else None,
                    "tool_trace": cot,
                    "premises": premises_nl,
                }

                return self.llm.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Write a concise, faithful explanation for an educational QA answer. "
                                "Mention the symbolic tool trace but do not invent premises."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(prompt, ensure_ascii=False),
                        },
                    ],
                    temperature=0,
                    max_tokens=700,
                )
            except Exception:
                pass

        if atom:
            chain = kb.trace.get(atom, [])[-6:]

            if chain:
                return (
                    f"Z3/forward-chaining derives {atom.label()} from the cited premises, "
                    f"so the answer is {answer}. Trace: "
                    + " | ".join(chain)
                )

        if cot:
            return (
                f"The symbolic checker could not prove a stronger conclusion, so the answer is {answer}. "
                "Evidence: "
                + " | ".join(cot[:5])
            )

        return f"The available premises do not provide enough support for a stronger conclusion, so the answer is {answer}."


class LogicAgent:
    def __init__(self, llm: Optional[VLLMClient] = None, rag_path: Optional[str] = None):
        self.parser = LogicNLParserAgent(llm)
        self.reasoner = Z3ReasonerAgent()
        self.explainer = ExplanationAgent(llm)
        self.rag = LogicRAGRetriever(rag_path) if rag_path else LogicRAGRetriever(None)

    def _reason_once(
        self,
        question: str,
        premises_nl: List[str],
        premises_fol: Optional[List[str]] = None,
        fewshot_examples: Optional[List[Dict[str, Any]]] = None,
    ):
        kb, parsed = self.parser.build_kb(
            premises_nl,
            question,
            premises_fol,
            fewshot_examples=fewshot_examples,
        )

        fallback_query_atom = self.parser.fallback_parse_query(question)

        choices = split_choices(question)

        if choices:
            answer, atom, conf = self.reasoner.best_choice(kb, question, parsed)
        else:
            answer, atom, conf = self.reasoner.yes_no_unknown(kb, question, parsed, fallback_query_atom)

        kb.closure()

        return kb, parsed, answer, atom, conf

    def solve(
        self,
        question: str,
        premises_nl: List[str],
        premises_fol: Optional[List[str]] = None,
        exclude_record_index: Optional[int] = None,
        exclude_idx: Optional[Any] = None,
        use_rag: bool = True,
        question_index: Optional[int] = None,
        idx: Optional[Any] = None,
    ) -> Dict[str, Any]:
        focused_indices = None
        if idx is not None and question_index is not None:
            if isinstance(idx, dict):
                focused_indices = idx.get(str(question_index)) or idx.get(question_index)
            elif isinstance(idx, list) and len(idx) > question_index:
                focused_indices = idx[question_index]
                
        if focused_indices:
            focused_set = set(focused_indices)
            premises_nl = [p for i, p in enumerate(premises_nl, 1) if i in focused_set]
            if premises_fol:
                premises_fol = [p for i, p in enumerate(premises_fol, 1) if i in focused_set]

        qtype = classify_logic_question(question)
        type_prompt = prompt_for_type(qtype)

        # Stage 0: RAG retrieval first.
        # Retrieved examples are injected into the parser prompt as few-shot guidance.
        retrieved = self.rag.retrieve(
            question,
            premises_nl,
            top_k=3,
            exclude_record_index=exclude_record_index,
            exclude_idx=exclude_idx,
            exclude_question=question,
        ) if (use_rag and self.rag.enabled) else []

        # Stage 1: LLM Parser / provided FOL / regex fallback with RAG few-shot examples.
        kb, parsed, answer, atom, conf = self._reason_once(
            question,
            premises_nl,
            premises_fol,
            fewshot_examples=retrieved,
        )

        # Stage 2: conservative FOL fallback.
        # Only reuse FOL when retrieved example has exactly matching premises.
        rag_fol_used = None

        if (answer == "Unknown" or conf < 0.55) and not premises_fol and retrieved:
            rag_fol_used = self.rag.best_fol_if_same_premises(premises_nl, retrieved)

            if rag_fol_used:
                kb2, parsed2, answer2, atom2, conf2 = self._reason_once(
                    question,
                    premises_nl,
                    rag_fol_used,
                    fewshot_examples=retrieved,
                )

                if answer2 != "Unknown" or conf2 > conf:
                    kb, parsed, answer, atom, conf = (
                        kb2,
                        parsed2,
                        answer2,
                        atom2,
                        max(conf2, 0.78),
                    )

        cot: List[str] = []

        if atom:
            cot = kb.trace.get(atom, [f"Z3 checked entailment for {atom.label()}."])
        else:
            cot = [
                f"Classified logic question as {qtype}.",
                "Parsed premises into a Horn-rule knowledge base.",
                "Ran forward chaining and Z3 entailment checks.",
            ]

        if retrieved:
            cot.append(
                "RAG retrieved similar logic examples and injected them as few-shot parser guidance."
            )

        if rag_fol_used:
            cot.append(
                "RAG fallback reused FOL only because a retrieved example had matching premises."
            )

        if focused_indices:
            cot.append(f"Filtered premises using focused indices for this question: {focused_indices}")

        explanation = self.explainer.explain(question, answer, atom, kb, premises_nl, cot)
        fol_evidence = atom.label() if atom else None

        rag_context = [
            {
                "record_index": r.get("record_index"),
                "score": r.get("score"),
                "questions": r.get("questions", [])[:2],
                "answers": r.get("answers", [])[:2],
                "fol_count": len(r.get("premises-FOL", [])),
            }
            for r in retrieved
        ]

        return standard_response(
            answer,
            explanation,
            fol=fol_evidence,
            cot=cot,
            confidence=round(conf, 3),
            question_type=qtype,
            type_prompt=type_prompt,
            rag_used=bool(retrieved),
            rag_fol_used=bool(rag_fol_used),
            rag_context=rag_context,
            focused_indices=focused_indices,
        )