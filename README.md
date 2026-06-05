# EXACT 2026 RAG agents

This version adds leakage-safe RAG for both tasks:

- Logic: classify question type, build a prompt by question type, parse NL to Horn/FOL, run symbolic reasoning, then use a Logic RAG retriever only as fallback/pattern guidance.
- Physics: formula solver first, LLM parser/solver second, Physics RAG fallback third.

## Evaluation leakage control

During evaluation, every payload includes `__record_index` and, when available, `id`/`idx`. The RAG retrievers skip the current test row before ranking:

- Logic excludes `__record_index`, `idx`, and exact duplicate current question text.
- Physics excludes `__record_index`, `id`, and exact duplicate current question text.

This prevents the nearest-neighbor RAG step from retrieving the exact sample being evaluated and copying its gold answer.

## Run

```bash
python main.py eval \
  --logic data/Logic_Based_Educational_Queries.json \
  --physics data/Physics_Problems_Text_Only_removeQA.json \
  --max-records 20 \
  --no-fol \
  --details details.json
```

Use `--details` to inspect `rag_context` and verify retrieved examples are not the current record.
