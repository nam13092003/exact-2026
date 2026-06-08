from __future__ import annotations

import json
import re
import os
from typing import Any, Dict, List, Optional, Set, Tuple

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


# ---------------------------------------------------------------------------
# Negation / predicate extraction helpers  (Fix 1)
# ---------------------------------------------------------------------------

_NEG_PATTERNS = re.compile(
    r"\b(not|never|no longer|cannot|can not|hasn't|haven't|has not|have not|"
    r"does not|do not|did not|is not|are not|was not|were not)\b",
    re.I,
)
_AUX_STRIP = re.compile(
    r"^(has|have|had|is|are|was|were|will|would|can|could|should|must|"
    r"does|do|did|been|be|get|gets|got)\s+",
    re.I,
)
_QUANT_STRIP = re.compile(
    r"^(a|an|the|every|all|any|anyone|someone|each|if|then|person|people|one)\s+",
    re.I,
)


def _lemmatize_pred(p: str) -> str:
    """Very naive lemmatization for common verbs to help unify 'qualifies' vs 'qualified'."""
    p = re.sub(r"\b(is|are|was|were|be|been)\b", "be", p)
    p = re.sub(r"\b(has|have|had)\b", "have", p)
    p = re.sub(r"\b(does|do|did)\b", "do", p)
    p = re.sub(r"ies\b", "y", p)
    p = re.sub(r"ied\b", "y", p)
    p = re.sub(r"ed\b", "", p)
    p = re.sub(r"s\b", "", p)
    p = re.sub(r"_+", "_", p).strip("_")
    return p


def _lemma_norm(kb: HornKB) -> HornKB:
    """Normalizes all predicates in a HornKB to their base lemma to prevent exact-string mismatch (e.g. qualified vs qualifies)."""
    nkb = HornKB()
    for atom in kb.facts:
        nkb.add_fact(Atom(_lemmatize_pred(atom.pred), atom.args, atom.truth),
                     (kb.trace.get(atom) or [atom.label()])[0])
    for rule in kb.rules:
        nkb.add_rule(Rule(
            [Atom(_lemmatize_pred(a.pred), a.args, a.truth) for a in rule.antecedents],
            Atom(_lemmatize_pred(rule.consequent.pred), rule.consequent.args, rule.consequent.truth),
            rule.source,
        ))
    return nkb


def _fuzzy_closure(kb: HornKB) -> HornKB:
    """Fuzzy forward chaining that handles semantic drift in predicates and basic numerical thresholds."""
    _stop = {"a", "an", "the", "of", "at", "least", "above", "below", "per", "more", "than", "with", "has", "is", "are", "on", "time"}

    def _ptoks(p: str) -> frozenset:
        return frozenset(t for t in _lemmatize_pred(p).split("_") if t not in _stop and len(t) > 1)
        
    def _extract_num(s: str) -> Optional[float]:
        import re
        m = re.search(r'\d+(\.\d+)?', s)
        return float(m.group()) if m else None

    def _fuzzy_match(ant: Atom, known: set) -> Optional[Atom]:
        at = _ptoks(ant.pred)
        if not at:
            return None
        best_f, best_s = None, 0.0
        for f in known:
            if f.truth != ant.truth:
                continue
            if len(f.args) > 0 and len(ant.args) > 0:
                if f.args[0] != ant.args[0] and f.args[0] != "entity" and ant.args[0] != "entity":
                    continue
            elif len(f.args) != len(ant.args):
                continue
                
            # Arithmetic argument comparison (e.g. membership_duration 8 vs 6)
            num_ok = True
            for i in range(1, max(len(ant.args), len(f.args))):
                fa = f.args[i] if i < len(f.args) else ""
                aa = ant.args[i] if i < len(ant.args) else ""
                if fa != aa:
                    fn = _extract_num(fa)
                    an = _extract_num(aa)
                    if fn is not None and an is not None:
                        if fn < an: # If fact has 8, and ant requires 6. 8 >= 6 is OK. If fact has 4 and ant requires 6, fn < an -> FAIL
                            num_ok = False
                            break
                    else:
                        num_ok = False
                        break
            if not num_ok:
                continue
                
            ft = _ptoks(f.pred)
            if not ft:
                continue
            if at.issubset(ft):
                return f
            ov = len(at & ft) / max(1, len(at | ft))
            if ov >= 0.70 and ov > best_s:
                best_s, best_f = ov, f
        return best_f

    for _ in range(100):
        changed = False
        for rule in kb.rules:
            if rule.consequent in kb.facts:
                continue
            matched = []
            ok = True
            for ant in rule.antecedents:
                if ant in kb.facts:
                    matched.append(ant)
                else:
                    fz = _fuzzy_match(ant, kb.facts)
                    if fz is not None:
                        matched.append(fz)
                    else:
                        ok = False
                        break
            if ok:
                cons = rule.consequent
                if cons.args and cons.args[0] == "entity":
                    for mf in matched:
                        if mf.args and mf.args[0] != "entity":
                            cons = Atom(cons.pred, mf.args, cons.truth)
                            break
                if cons not in kb.facts:
                    chain = []
                    for mf in matched:
                        chain.extend(kb.trace.get(mf, [mf.label()]))
                    chain.append(f"Rule: {rule.source} => {cons.label()}")
                    kb.add_fact(cons, " | ".join(chain))
                    changed = True
        if not changed:
            break
    return kb

def _extract_negation(text: str) -> Tuple[bool, str]:
    if _NEG_PATTERNS.search(text):
        cleaned = _NEG_PATTERNS.sub("", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return False, cleaned
    return True, text


def _strip_leading_junk(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _QUANT_STRIP.sub("", text).strip()
        text = _AUX_STRIP.sub("", text).strip()
    return text


def _parse_premise_part(text: str) -> Tuple[str, str, bool]:
    """Return (snake_case_pred, entity_constant, truth)."""
    text = text.strip().rstrip(".")
    truth, text = _extract_negation(text)

    entity = "entity"
    text_no_title = re.sub(
        r"^(professor|dr\.|dr |mr\.|mr |ms\.|ms |mrs\.|mrs )",
        "", text, flags=re.I,
    ).strip()

    m_named = re.match(r"([A-Z][A-Za-z0-9]+)\s+(.*)", text_no_title)
    if m_named:
        entity = pred_name(m_named.group(1))
        pred_text = m_named.group(2)
    else:
        pred_text = text

    pred_text = _strip_leading_junk(pred_text).strip()
    pred_text = re.sub(r"^(person|someone|people|each person|one)\s+", "", pred_text, flags=re.I).strip()
    pred_text = _AUX_STRIP.sub("", pred_text).strip()
    pred_text = re.sub(r"^they\s+", "", pred_text, flags=re.I)
    pred_text = _AUX_STRIP.sub("", pred_text).strip()

    return pred_name(pred_text) or "predicate", entity, truth


# ---------------------------------------------------------------------------
# Fix 3: Universal-fact YesNo check
# ---------------------------------------------------------------------------

_UNIVERSAL_Q_PATTERNS = [
    re.compile(r"^(?:have|has|do|does|are|is|did|will|would)\s+all\s+\w+\s+(.+)\??$", re.I),
    re.compile(r"^are\s+all\s+\w+\s+(.+)\??$", re.I),
    re.compile(r"^(?:do|does|will|would|can)\s+everyone\s+(.+)\??$", re.I),
    re.compile(r"^(?:have|has)\s+everyone\s+(.+)\??$", re.I),
]


def _check_universal_yes(question: str, kb: HornKB) -> Optional[Tuple[str, Optional[Atom], float]]:
    q = question.strip().rstrip("?!.")
    q = re.split(r",\s*according\b", q, flags=re.I)[0].strip()

    for pat in _UNIVERSAL_Q_PATTERNS:
        m = pat.match(q)
        if not m:
            continue
        pred_raw = m.group(1).strip()
        pred_raw = _AUX_STRIP.sub("", pred_raw).strip()
        pred_raw = re.sub(r"^(been|be)\s+", "", pred_raw, flags=re.I).strip()
        target_pred = pred_name(pred_raw)
        if not target_pred:
            continue
        target_lemma = _lemmatize_pred(target_pred)
        tgt_words = set(target_lemma.split("_")) - {"a", "an", "the"}

        kb.closure()
        for atom in kb.facts:
            if not atom.truth:
                continue
            if atom.pred == target_pred:
                return "Yes", atom, 0.82
            if _lemmatize_pred(atom.pred) == target_lemma:
                return "Yes", atom, 0.82
            aw = set(_lemmatize_pred(atom.pred).split("_")) - {"a", "an", "the"}
            if tgt_words and aw and len(tgt_words & aw) / max(1, len(tgt_words | aw)) >= 0.60:
                return "Yes", atom, 0.72

    return None


# ---------------------------------------------------------------------------
# Fix 5: Statement / chain question handlers (CWA)
# ---------------------------------------------------------------------------

_STATEMENT_Q_PATTERNS = [
    re.compile(
        r"(?:is\s+(?:the\s+)?(?:following\s+)?statement\s+(?:true|correct|valid).*?)\n?Statement:\s*(.+)$",
        re.I | re.S,
    ),
    re.compile(r"^is\s+it\s+true\s+that\s+(.+)\??$", re.I),
]

_CHAIN_Q_PATTERNS = [
    re.compile(
        r"does?\s+(.+?)\s+initiate\s+a\s+causal\s+chain\s+leading\s+to\s+(.+?)[,\.]?\??$",
        re.I,
    ),
    re.compile(
        r"is\s+there\s+a\s+logical\s+(?:chain|path|pathway)\s+from\s+(.+?)\s+to\s+(.+?)[,\.]?\??$",
        re.I,
    ),
]


def _extract_statement(question: str) -> Optional[str]:
    """Return statement body only for well-defined CWA patterns (avoids regressions)."""
    q = question.strip()

    for pat in _STATEMENT_Q_PATTERNS:
        m = pat.search(q)
        if m:
            return m.group(1).strip().rstrip("?.")

    idx = q.find("Statement:")
    if idx != -1:
        return q[idx + len("Statement:"):].strip().rstrip("?.")

    m_it = re.match(r"^is\s+it\s+true\s+that\s+(.+)\??$", q, re.I)
    if m_it:
        return m_it.group(1).strip().rstrip("?.")

    if re.search(r"\b(?:guarantee|guarantees|ensure|ensures|sufficient|alone\s+(?:is|be)\s+sufficient)\b", q, re.I):
        return q.rstrip("?.")

    m_self = re.match(r"^(.{30,}?)\.\s*Is\s+(?:this\s+)?(?:the\s+)?statement\s+true\??$", q, re.I | re.S)
    if m_self:
        return m_self.group(1).strip()

    m_follow = re.match(r"^does\s+it\s+follow\s+that\s+(.+?)(?:,\s*according\b.*)?\??$", q, re.I)
    if m_follow:
        return m_follow.group(1).strip().rstrip("?.")

    if (re.match(r"^if\b", q, re.I) and
            re.search(r"\b(?:is\s+(?:this\s+)?(?:statement|claim|conclusion)\s+(?:true|valid|correct))\b", q, re.I)):
        return q.rstrip("?.")

    return None


def _statement_cwa_check(statement: str, kb: HornKB) -> Optional[Tuple[str, float]]:
    """CWA check: if not derivable from KB → No."""
    kb.closure()
    if not kb.facts and not kb.rules:
        return "Unknown", 0.35

    stmt = statement.strip().rstrip(".")

    # "All X do Y" universal
    m_all = re.match(r"^(?:all|every(?:one|body)?)\s+\w+\s+(.+)$", stmt, re.I)
    if m_all:
        cons_raw = m_all.group(1).strip()
        target = pred_name(cons_raw)
        tgt_toks = set(_lemmatize_pred(target).split("_")) - {"a", "an", "the"}
        for atom in kb.facts:
            if not atom.truth:
                continue
            at = set(_lemmatize_pred(atom.pred).split("_")) - {"a", "an", "the"}
            if tgt_toks and at and len(tgt_toks & at) / max(1, len(tgt_toks | at)) >= 0.65:
                return "Yes", 0.82
        return "No", 0.70

    # "If X then Y"
    parts = re.split(r",?\s*then\s+", stmt, maxsplit=1, flags=re.I)
    if len(parts) == 2:
        hyp_str = re.sub(r"^if\s+", "", parts[0], flags=re.I).strip()
        goal_str = parts[1].strip()
        tmp_kb = HornKB()
        tmp_kb.facts = set(kb.facts)
        tmp_kb.rules = list(kb.rules)
        tmp_kb.trace = dict(kb.trace)
        hp, he, ht = _parse_premise_part(hyp_str)
        tmp_kb.add_fact(Atom(hp, (he,), ht), f"Hypothesis: {hyp_str}")
        tmp_kb.closure()
        gp, ge, gt = _parse_premise_part(goal_str)
        for ent in [he, ge, "entity"]:
            r = tmp_kb.entails(Atom(gp, (ent,), gt))
            if r is True:
                return "Yes", 0.82
            if r is False:
                return "No", 0.82
        if not kb.rules:
            return "Unknown", 0.40
        return "No", 0.72

    # "There exists X"
    m_ex = re.match(r"^there\s+exists?\s+(?:at\s+least\s+one\s+)?(.+)$", stmt, re.I)
    if m_ex:
        pp, _, pt = _parse_premise_part(m_ex.group(1).strip())
        toks = set(_lemmatize_pred(pp).split("_")) - {"a", "an", "the"}
        for atom in kb.facts:
            if not atom.truth:
                continue
            aw = set(_lemmatize_pred(atom.pred).split("_")) - {"a", "an", "the"}
            if toks and aw and len(toks & aw) / max(1, len(toks | aw)) >= 0.55:
                return "Yes", 0.75
        return "No", 0.72

    # Atomic claim
    ap, ae, at_ = _parse_premise_part(stmt)
    for ent in [ae, "entity"]:
        r = kb.entails(Atom(ap, (ent,), at_))
        if r is True:
            return "Yes", 0.80
        if r is False:
            return "No", 0.80
    return "No", 0.68


def _chain_question_check(question: str, kb: HornKB) -> Optional[Tuple[str, float]]:
    """Check 'Does X initiate a chain leading to Y?' — CWA on focused premises."""
    q = question.strip().rstrip("?.")
    q = re.split(r",?\s*according\b", q, flags=re.I)[0].strip()

    for pat in _CHAIN_Q_PATTERNS:
        m = pat.match(q)
        if not m or pat.groups < 2:
            continue
        start_str, end_str = m.group(1).strip(), m.group(2).strip()
        tmp_kb = HornKB()
        tmp_kb.facts = set(kb.facts)
        tmp_kb.rules = list(kb.rules)
        tmp_kb.trace = dict(kb.trace)
        sp, se, st = _parse_premise_part(start_str)
        tmp_kb.add_fact(Atom(sp, (se,), st), f"Hypothesis: {start_str}")
        tmp_kb.closure()
        ep, ee, et = _parse_premise_part(end_str)
        for ent in [se, ee, "entity"]:
            if tmp_kb.entails(Atom(ep, (ent,), et)) is True:
                return "Yes", 0.80
        end_words = set(_lemmatize_pred(ep).split("_")) - {"a", "an", "the"}
        for atom in tmp_kb.facts:
            if not atom.truth:
                continue
            aw = set(_lemmatize_pred(atom.pred).split("_")) - {"a", "an", "the"}
            if end_words and aw and len(end_words & aw) / max(1, len(end_words | aw)) >= 0.65:
                return "Yes", 0.72
        return "No", 0.72

    return None


# ---------------------------------------------------------------------------
# LogicNLParserAgent
# ---------------------------------------------------------------------------

class LogicNLParserAgent:
    """Convert natural-language premises/questions to compact Horn-logic JSON."""

    def __init__(self, llm: Optional[VLLMClient] = None):
        self.llm = llm or VLLMClient()

    def _build_fewshot_payload(self, fewshot_examples=None):
        fewshots = []
        for ex in (fewshot_examples or [])[:3]:
            fewshots.append({
                "similar_record_index": ex.get("record_index"),
                "similar_score": ex.get("score"),
                "similar_premises_nl": ex.get("premises-NL", [])[:8],
                "similar_premises_fol": ex.get("premises-FOL", [])[:12],
                "similar_questions": ex.get("questions", [])[:2],
                "similar_answers": ex.get("answers", [])[:2],
                "similar_explanation": ex.get("explanation", [])[:2],
            })
        return fewshots

    def parse_with_llm(self, premises_nl, question, fewshot_examples=None):
        if not self.llm.enabled:
            return None

        # Simplified prompt for small models (<=8B):
        # Only ask for facts + rules. NO choices, NO query.
        # Small models fail when asked to do too many things at once.
        # The symbolic engine will handle answer selection.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        premises_text = "\n".join(f"{i+1}. {p}" for i, p in enumerate(premises_nl))
        
        with open(os.path.join(base_dir, "prompts", "logic_parser_system.txt"), "r", encoding="utf-8") as f:
            system_msg = f.read()
            
        with open(os.path.join(base_dir, "prompts", "logic_parser_user.txt"), "r", encoding="utf-8") as f:
            user_msg = f.read().replace("{premises_text}", premises_text).replace("{question}", question)

        try:
            text = self.llm.chat(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = extract_json(text)
            return parsed
        except Exception:
            return None

    def _validate_and_patch(self, parsed: Dict[str, Any], premises_nl: List[str]) -> Dict[str, Any]:
        """Fix 4b: inject missing negative facts the LLM omitted."""
        existing: Set[Tuple[str, Tuple, bool]] = set()
        for f in parsed.get("facts", []):
            pk = pred_name(str(f.get("pred", "")))
            existing.add((pk, tuple(pred_name(str(x)) for x in f.get("args", ["entity"])), bool(f.get("truth", True))))

        patched = list(parsed.get("facts", []))
        for i, p in enumerate(premises_nl, 1):
            truth, _ = _extract_negation(p)
            if truth:
                continue
            pp, pe, _ = _parse_premise_part(p)
            pl = _lemmatize_pred(pp)
            pt = set(pl.split("_"))
            already = False
            for (ek, _, et) in existing:
                if et is not False:
                    continue
                ek_toks = set(_lemmatize_pred(ek).split("_"))
                if pt and ek_toks and len(pt & ek_toks) / max(1, len(pt | ek_toks)) >= 0.55:
                    already = True
                    break
            if not already:
                patched.append({"pred": pp, "args": [pe], "truth": False,
                                "source": f"Premise {i} [auto-patched negation]: {p}"})
        parsed["facts"] = patched
        return parsed

    def fallback_parse_premises(self, premises_nl: List[str]) -> HornKB:
        kb = HornKB()

        for i, p in enumerate(premises_nl, 1):
            src = f"Premise {i}: {p}"
            s = p.strip().rstrip(".")

            # --- If A then B ---
            m = re.match(r"if\s+(.+?)(?:,?\s+then\s+|,\s+)(.+)$", s, flags=re.I)
            if not m:
                m = re.match(r"(.+?)\s+implies\s+(.+)$", s, flags=re.I)
            if m:
                ant_str, cons_str = m.group(1), m.group(2)
                ants: List[Atom] = []
                for a in re.split(r"\s+and\s+", ant_str, flags=re.I):
                    ap, ae, at = _parse_premise_part(a)
                    ants.append(Atom(ap, (ae,), at))
                cp, ce, ct = _parse_premise_part(cons_str)
                if ce == "entity" and ants and re.match(r"^(they|he|she|it)\b", cons_str.strip(), re.I):
                    if ants[0].args[0] != "entity":
                        ce = ants[0].args[0]
                kb.add_rule(Rule(ants, Atom(cp, (ce,), ct), src))
                continue

            # --- Fix A: "Noun who X and Y are Z" relative-clause ---
            m = re.match(
                r"^(students?|people|person|drivers?|faculty|staff|members?|"
                r"researchers?|schools?|professors?|nurses?|engineers?|teachers?)\s+"
                r"who\s+(.+?)\s+(?:are|is|can|will|qualify|become|receive|get)\s+(.+)$",
                s, flags=re.I,
            )
            if m:
                ant_str, cons_text = m.group(2).strip(), m.group(3).strip()
                ants = []
                for a in re.split(r"\s+and\s+", ant_str, flags=re.I):
                    ap, _, at = _parse_premise_part(a)
                    ants.append(Atom(ap, ("entity",), at))
                cp, _, ct = _parse_premise_part(cons_text)
                kb.add_rule(Rule(ants, Atom(cp, ("entity",), ct), src))
                continue

            # --- All / Every X verb Y (any verb) ---
            m = re.match(r"(?:all|every(?:one|body)?)\s+(.+?)\s+(?:are|is|will|can|has|have|do|does)\s+(.+)$", s, flags=re.I)
            if not m:
                m = re.match(r"(?:all|every(?:one|body)?)\s+(\w+)\s+(\w+(?:\s+.+)?)$", s, flags=re.I)
            if m:
                ant_text, cons_text = m.group(1).strip(), m.group(2).strip()
                if re.match(r"(one|body|one\b)$", ant_text, re.I) or ant_text == "":
                    cp, _, ct = _parse_premise_part(cons_text)
                    kb.add_fact(Atom(cp, ("entity",), ct), src)
                else:
                    ant = pred_name(ant_text)
                    cp, _, ct = _parse_premise_part(cons_text)
                    kb.add_rule(Rule([Atom(ant, ("entity",), True)], Atom(cp, ("entity",), ct), src))
                    kb.add_fact(Atom(ant, ("entity",), True), src)
                continue

            # --- Everyone will X ---
            m = re.match(r"everyone\s+(.+)$", s, flags=re.I)
            if m:
                cp, _, ct = _parse_premise_part(m.group(1))
                kb.add_fact(Atom(cp, ("entity",), ct), src)
                continue

            # --- Named entity fact ---
            if re.match(r"^(if|all|every|anyone|any|students|a|an|the)\b", s, flags=re.I):
                continue
            m = re.match(r"(?:professor\s+|dr\.\s+|dr\s+|mr\.\s+)?([A-Z][A-Za-z0-9_]+)\s+(.+)$", s)
            if m:
                fp, _, ft = _parse_premise_part(m.group(2))
                name = pred_name(m.group(1))
                kb.add_fact(Atom(fp, (name,), ft), src)

        kb = _lemma_norm(kb)
        kb = _fuzzy_closure(kb)
        kb.closure()
        return kb

    def fallback_parse_query(self, question: str) -> Optional[Atom]:
        q = question.strip().rstrip("?!.").lower()
        q = re.split(r",?\s*according\b", q, flags=re.I)[0].strip()
        q_truth = True
        if re.search(r"\bnot\b", q):
            q_truth = False
            q = re.sub(r"\bnot\b", "", q).strip()
        m = re.match(
            r"^(?:can|could|does|did|is|are|will|would|should|has|have)\s+"
            r"(?:a\s+|an\s+|the\s+)?([a-z0-9_]+(?:_[a-z0-9_]+)*)\s+(.+)$", q,
        )
        if m:
            entity = pred_name(m.group(1))
            phrase = pred_name(m.group(2))
            phrase = re.sub(r"^(be|been|have|has)_", "", phrase)
            return Atom(phrase, (entity,), q_truth)
        return None

    def build_kb(self, premises_nl, question, premises_fol=None, fewshot_examples=None):
        # First try fallback parser (fast, no API cost)
        kb_fallback = self.fallback_parse_premises(premises_nl)
        fallback_query_atom = self.fallback_parse_query(question)
        choices = split_choices(question)

        # Quick check: can fallback answer confidently?
        if choices:
            from tools.z3_logic import Atom as _Atom
            # Check if any choice atom is formally entailed
            for label, text in choices.items():
                pass  # will be checked by reasoner
        
        # Since we are using a highly capable model (Gemini 3.1 Pro), we re-enable the JSON logic parsing.
        parsed = self.parse_with_llm(premises_nl, question, fewshot_examples=fewshot_examples)
        if parsed:
            kb = HornKB()
            
            # Step 1: Collect domain from facts
            domain = set()
            for f in parsed.get("facts", []):
                if not isinstance(f, dict):
                    continue
                for x in f.get("args", ["entity"]):
                    domain.add(pred_name(str(x)))
            if not domain:
                domain.add("entity")

            # Step 2: Add facts
            for f in parsed.get("facts", []):
                if not isinstance(f, dict):
                    continue
                kb.add_fact(
                    Atom(pred_name(str(f.get("pred", "predicate"))),
                         tuple(pred_name(str(x)) for x in f.get("args", ["entity"])),
                         bool(f.get("truth", True))),
                    f.get("source", "LLM fact"),
                )
            
            # Step 3: Add rules instantiated over the domain
            for r in parsed.get("rules", []):
                if not isinstance(r, dict):
                    continue

                if_clause = r.get("if", [])
                if isinstance(if_clause, dict):
                    if_clause = [if_clause]
                elif not isinstance(if_clause, list):
                    if_clause = []

                ants_template = [Atom(pred_name(str(a.get("pred", "predicate"))),
                            tuple(pred_name(str(x)) for x in a.get("args", ["entity"])),
                            bool(a.get("truth", True)))
                        for a in if_clause if isinstance(a, dict)]

                th = r.get("then", {})
                if isinstance(th, list):
                    th = th[0] if th else {}
                elif not isinstance(th, dict):
                    th = {}

                if ants_template and th:
                    cons_template = Atom(
                        pred_name(str(th.get("pred", "predicate"))),
                        tuple(pred_name(str(x)) for x in th.get("args", ["entity"])),
                        bool(th.get("truth", True))
                    )
                    
                    # Instantiate for each constant in domain
                    for const in domain:
                        def sub(args_tup):
                            return tuple(const if x == "entity" else x for x in args_tup)
                            
                        inst_ants = [Atom(a.pred, sub(a.args), a.truth) for a in ants_template]
                        inst_cons = Atom(cons_template.pred, sub(cons_template.args), cons_template.truth)
                        kb.add_rule(Rule(inst_ants, inst_cons, r.get("source", "LLM rule")))
            
            # Apply lemma normalization to fix LLM verb tense fluctuations (e.g. qualified vs qualifies)
            kb = _lemma_norm(kb)
            kb = _fuzzy_closure(kb)
            kb.closure()
            return kb, parsed

        if premises_fol:
            return parse_fol_to_kb(premises_fol), None

        return kb_fallback, None


# ---------------------------------------------------------------------------
# json_atom_to_atom
# ---------------------------------------------------------------------------

def json_atom_to_atom(obj: Any) -> Optional[Atom]:
    if not isinstance(obj, dict) or not obj.get("pred"):
        return None
    return Atom(
        pred_name(str(obj.get("pred"))),
        tuple(pred_name(str(x)) for x in obj.get("args", ["entity"])),
        bool(obj.get("truth", True)),
    )


# ---------------------------------------------------------------------------
# Z3ReasonerAgent  (Fix 2 + Fix C + Fix 6)
# ---------------------------------------------------------------------------

class Z3ReasonerAgent:

    def answer_atom(self, kb: HornKB, atom: Atom) -> str:
        ent = kb.entails(atom)
        if ent is True:
            return "Yes"
        if ent is False:
            return "No"
        return "Unknown"

    def _contradiction_check(self, kb: HornKB, atom: Atom, answer: str) -> str:
        """Fix 2a: if KB entails both atom and ¬atom → Unknown."""
        if answer not in ("Yes", "No"):
            return answer
        if kb.entails(atom) is True and kb.entails(atom.neg()) is True:
            return "Unknown"
        return answer

    def _has_blocking_negatives(self, kb: HornKB) -> bool:
        kb.closure()
        return any(not f.truth for f in kb.facts)

    def best_choice(self, kb: HornKB, question: str, parsed) -> Tuple[str, Optional[Atom], float]:
        choices = split_choices(question)
        if not choices:
            return "Unknown", None, 0.25

        if parsed and isinstance(parsed.get("choices"), dict):
            for label, obj in parsed["choices"].items():
                atom = json_atom_to_atom(obj)
                if atom and kb.entails(atom) is True:
                    if kb.entails(atom.neg()) is True:
                        continue
                    return label, atom, 0.85

        kb.closure()
        positive_atoms = [a for a in kb.facts if a.truth]
        best: Tuple[str, Optional[Atom], float] = ("Unknown", None, 0.0)

        for label, text in choices.items():
            tw = tokenize(text)
            score, best_atom = 0.0, None
            for atom in positive_atoms:
                aw = atom_words(atom)
                if not aw:
                    continue
                overlap = len(tw & aw) / max(1, len(tw | aw))
                if overlap > score:
                    score, best_atom = overlap, atom
            if re.search(r"\b(needs?|cannot|not|insufficient|lacks?)\b", text, flags=re.I):
                if best_atom and best_atom.truth:
                    score *= 0.65
            if score > best[2]:
                best = (label, best_atom, score)

        # Fix 6: only commit when overlap is meaningful
        if best[2] >= 0.35:
            return best[0], best[1], min(0.65, 0.35 + best[2])
        return "Unknown", None, 0.28

    def yes_no_unknown(
        self,
        kb: HornKB,
        question: str,
        parsed,
        fallback_query_atom: Optional[Atom] = None,
        premises_nl: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[Atom], float]:

        # Fix 5a: causal chain check
        chain_result = _chain_question_check(question, kb)
        if chain_result is not None:
            return chain_result[0], None, chain_result[1]

        # Fix 5b: statement CWA check
        stmt = _extract_statement(question)
        if stmt:
            res = _statement_cwa_check(stmt, kb)
            if res is not None:
                return res[0], None, res[1]

        # Fix 3: universal-fact check
        uni = _check_universal_yes(question, kb)
        if uni is not None:
            return uni

        # Fix C: "meets all requirements / qualify to" → CWA mode
        _ALL_REQ = re.compile(
            r"\b(meets?\s+all\s+requirements?|qualif(?:y|ies)\s+(?:to|for)|"
            r"eligible\s+to|make\s+(?:him|her|them)\s+eligible|"
            r"all\s+requirements?\s+for|all\s+the\s+requirements?)\b", re.I)
        _CHAIN_DEMO = re.compile(
            r"\b(logical\s+(?:chain|sequence|progression|flow)|demonstrates?\s+that)\b", re.I)
        cwa_mode = bool(_ALL_REQ.search(question) and not _CHAIN_DEMO.search(question))

        # LLM-parsed query
        if parsed:
            atom = json_atom_to_atom(parsed.get("query"))
            if atom:
                raw = self.answer_atom(kb, atom)
                raw = self._contradiction_check(kb, atom, raw)
                return raw, atom, 0.85

        # Fallback query atom alignment
        if fallback_query_atom:
            kb_preds = {f.pred for f in kb.facts} | \
                       {r.consequent.pred for r in kb.rules} | \
                       {a.pred for r in kb.rules for a in r.antecedents}
            tw = tokenize(fallback_query_atom.pred.replace("_", " "))
            best_pred, best_sc = fallback_query_atom.pred, 0.0
            for kp in kb_preds:
                kw = tokenize(kp.replace("_", " "))
                if kw and tw:
                    ov = len(tw & kw) / max(1, len(tw | kw))
                    if ov > best_sc and ov > 0.3:
                        best_sc, best_pred = ov, kp
            aligned = Atom(best_pred, fallback_query_atom.args, fallback_query_atom.truth)
            ent = kb.entails(aligned)
            if ent is True:
                if kb.entails(aligned.neg()) is True:
                    return "Unknown", aligned, 0.45
                return "Yes", aligned, 0.85
            if ent is False:
                return "No", aligned, 0.85

        # Token-overlap fallback
        qw = tokenize(question)
        kb.closure()
        best_atom, best_score = None, 0.0
        for atom in kb.facts:
            aw = atom_words(atom)
            score = len(qw & aw) / max(1, len(qw | aw))
            if score > best_score:
                best_score, best_atom = score, atom

        if best_atom and best_score >= 0.10:
            answer = "Yes" if best_atom.truth else "No"
            conf = min(0.7, 0.35 + best_score)
            
            if cwa_mode and answer == "Yes":
                # In CWA mode, fuzzy match is not sufficient to prove "Yes"
                return "No", best_atom, 0.65
                
            if answer == "Yes" and conf < 0.60 and self._has_blocking_negatives(kb):
                return ("No" if cwa_mode else "Unknown"), best_atom, 0.55
            return answer, best_atom, conf

        if cwa_mode:
            return "No", None, 0.65
        return "Unknown", None, 0.25


# ---------------------------------------------------------------------------
# ExplanationAgent
# ---------------------------------------------------------------------------

class ExplanationAgent:
    def __init__(self, llm: Optional[VLLMClient] = None):
        self.llm = llm or VLLMClient()

    def explain(self, question, answer, atom, kb, premises_nl, cot) -> str:
        if self.llm.enabled:
            try:
                prompt = {
                    "question": question, "answer": answer,
                    "entailed_atom": atom.label() if atom else None,
                    "tool_trace": cot, "premises": premises_nl,
                }
                return self.llm.chat(
                    [{"role": "system", "content": (
                        "Write a concise, faithful explanation for an educational QA answer. "
                        "Mention the symbolic tool trace but do not invent premises.")},
                     {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
                    temperature=0, max_tokens=700,
                )
            except Exception:
                pass

        if atom:
            chain = kb.trace.get(atom, [])[-6:]
            if chain:
                return (f"Z3/forward-chaining derives {atom.label()} from the cited premises, "
                        f"so the answer is {answer}. Trace: " + " | ".join(chain))

        if cot:
            return (f"The symbolic checker could not prove a stronger conclusion, "
                    f"so the answer is {answer}. Evidence: " + " | ".join(cot[:5]))

        return f"The available premises do not provide enough support, so the answer is {answer}."


# ---------------------------------------------------------------------------
# LogicAgent
# ---------------------------------------------------------------------------

class LogicAgent:
    def __init__(self, llm: Optional[VLLMClient] = None, rag_path: Optional[str] = None):
        self.llm = llm or VLLMClient()
        self.parser = LogicNLParserAgent(llm)
        self.reasoner = Z3ReasonerAgent()
        self.explainer = ExplanationAgent(llm)
        self.rag = LogicRAGRetriever(rag_path) if rag_path else LogicRAGRetriever(None)

    def _reason_once(self, question, premises_nl, premises_fol=None, fewshot_examples=None):
        kb, parsed = self.parser.build_kb(premises_nl, question, premises_fol,
                                          fewshot_examples=fewshot_examples)
        fallback_query_atom = self.parser.fallback_parse_query(question)
        choices = split_choices(question)

        if choices:
            answer, atom, conf = self.reasoner.best_choice(kb, question, parsed)
        else:
            answer, atom, conf = self.reasoner.yes_no_unknown(
                kb, question, parsed, fallback_query_atom, premises_nl)

        kb.closure()
        return kb, parsed, answer, atom, conf

    def _solve_meta_logic(self, question: str, premises_nl: str) -> Tuple[str, float, str]:
        """Bypass Z3 entirely and use LLM directly for Meta-Logic queries like counting premises."""
        import os
        
        system_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "logic_meta_system.txt")
        user_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "logic_meta_user.txt")
        
        try:
            with open(system_path, "r", encoding="utf-8") as f:
                sys_prompt = f.read()
            with open(user_path, "r", encoding="utf-8") as f:
                user_template = f.read()
        except FileNotFoundError:
            return "Unknown", 0.0, "Missing meta logic prompts."
            
        user_prompt = user_template.format(premises=premises_nl, question=question)
        
        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = self.llm.chat(messages, temperature=0.0)
            import json, re
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                ans = str(data.get("answer", "Unknown")).strip()
                reasoning = str(data.get("reasoning", ""))
                return ans, 0.9, reasoning
            else:
                return "Unknown", 0.0, "Failed to parse LLM JSON."
        except Exception as e:
            print(f"MetaLogic error: {e}")
            return "Unknown", 0.0, f"Error: {e}"

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

        original_premises_nl = list(premises_nl)

        # --- Filter to focused premises when idx is provided ---
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

        # Stage 0: RAG
        retrieved = (
            self.rag.retrieve(question, original_premises_nl, top_k=3,
                              exclude_record_index=exclude_record_index,
                              exclude_idx=exclude_idx, exclude_question=question)
            if (use_rag and self.rag.enabled) else []
        )
        
        # MetaLogic Bypass
        if qtype == "MetaLogic":
            answer, conf, reasoning = self._solve_meta_logic(question, premises_nl)
            return standard_response(
                answer, f"Meta-Logic question detected. Z3 bypassed. LLM Reasoning: {reasoning}",
                fol=None, cot=["MetaLogic bypass active. Answered directly by LLM."],
                confidence=conf, question_type=qtype, type_prompt=type_prompt,
                rag_used=False, rag_fol_used=False, rag_context=[], focused_indices=focused_indices
            )

        # Stage 1: Symbolic fallback parser + Z3 (no LLM, always runs)
        kb, parsed, answer, atom, conf = self._reason_once(
            question, premises_nl, premises_fol, fewshot_examples=retrieved)

        # Stage 2: RAG-FOL fallback (same-premise only, no LLM)
        rag_fol_used = None
        if (answer == "Unknown" or conf < 0.55) and not premises_fol and retrieved:
            rag_fol_used = self.rag.best_fol_if_same_premises(original_premises_nl, retrieved)
            if rag_fol_used:
                if focused_indices:
                    focused_set = set(focused_indices)
                    filtered_rag_fol = [p for i, p in enumerate(rag_fol_used, 1) if i in focused_set]
                else:
                    filtered_rag_fol = rag_fol_used
                    
                kb2, parsed2, answer2, atom2, conf2 = self._reason_once(
                    question, premises_nl, filtered_rag_fol, fewshot_examples=retrieved)
                if answer2 != "Unknown" or conf2 > conf:
                    kb, parsed, answer, atom, conf = kb2, parsed2, answer2, atom2, max(conf2, 0.78)

        # Z3 makes the final absolute decision. No LLM direct reader override allowed.
        llm_used = False

        # Build CoT
        cot: List[str] = []
        if atom:
            cot = kb.trace.get(atom, [f"Z3 checked entailment for {atom.label()}."])
        else:
            cot = [f"Classified logic question as {qtype}.",
                   "Parsed premises into a Horn-rule knowledge base.",
                   "Ran forward chaining and Z3 entailment checks."]
        if retrieved:
            cot.append("RAG retrieved similar logic examples as few-shot parser guidance.")
        if rag_fol_used:
            cot.append("RAG fallback reused FOL because retrieved example had matching premises.")
        if llm_used:
            cot.append("LLM direct-reader used as fallback for uncertain symbolic result.")
        if focused_indices:
            cot.append(f"Filtered premises using focused indices: {focused_indices}")

        explanation = self.explainer.explain(question, answer, atom, kb, premises_nl, cot)
        fol_evidence = atom.label() if atom else None

        rag_context = [
            {"record_index": r.get("record_index"), "score": r.get("score"),
             "questions": r.get("questions", [])[:2], "answers": r.get("answers", [])[:2],
             "fol_count": len(r.get("premises-FOL", []))}
            for r in retrieved
        ]

        return standard_response(
            answer, explanation,
            fol=fol_evidence, cot=cot,
            confidence=round(conf, 3),
            question_type=qtype,
            type_prompt=type_prompt,
            rag_used=bool(retrieved),
            rag_fol_used=bool(rag_fol_used),
            rag_context=rag_context,
            focused_indices=focused_indices,
        )
