from __future__ import annotations

import re
from typing import Dict

QUESTION_TYPES = ["YesNo", "MultiChoice", "Numerical", "ChainedQuestion", "OpenEnded", "MetaLogic"]

TYPE_PROMPTS: Dict[str, str] = {
    "YesNo": "Decide whether the queried proposition is entailed, contradicted, or unknown from the premises. Return Yes/No/Unknown and cite premise indices.",
    "MultiChoice": "Evaluate each option independently against the premises. Choose the single option that is best supported; if none is entailed, return Unknown.",
    "Numerical": "Extract quantities and symbolic relations, calculate deterministically, then return only the final number/unit.",
    "ChainedQuestion": "Break the question into ordered subclaims. Derive intermediate conclusions before the final answer, citing premises at each step.",
    "OpenEnded": "Produce a concise conclusion supported only by the premises; avoid unsupported outside knowledge.",
    "MetaLogic": "Analyze the meta-logical properties (e.g. number of premises, contradiction, tautology) and return the precise answer.",
}


def classify_logic_question(question: str) -> str:
    q = (question or "").strip()
    q_lower = q.lower()
    if re.search(r"\b(fewest premises|most premises|contradictory|tautology|how many steps)\b", q_lower):
        return "MetaLogic"
    if re.search(r"(?:^|\n)\s*[A-D]\.\s+", q):
        return "MultiChoice"
    if re.search(r"\b(calculate|compute|how many|how much|number|count|sum|difference|ratio|percentage)\b", q_lower):
        return "Numerical"
    if re.match(r"^(does|do|did|is|are|was|were|can|could|should|must|will|would|has|have)\b", q_lower):
        return "YesNo"
    if re.search(r"\b(first|after that|step|subquestion|part\s*[a-z0-9]|following chain|multi-part)\b", q_lower):
        return "ChainedQuestion"
    if "according to the premises" in q_lower and q_lower.endswith("?"):
        return "YesNo"
    return "OpenEnded"


def prompt_for_type(qtype: str) -> str:
    return TYPE_PROMPTS.get(qtype, TYPE_PROMPTS["OpenEnded"])
