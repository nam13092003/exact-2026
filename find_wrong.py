import json
with open("debug_logic_eval_full.json", "r", encoding="utf-8") as f:
    data = json.load(f)
for row in data.get("rows", []):
    if not row.get("ok", True):
        print(f"Q: {row['question'][:100]}")
        print(f"Gold: {row['gold']}")
        print(f"Pred: {row['pred']}")
        print(f"Type: {row.get('question_type', 'N/A')}")
        print(f"FOL: {row.get('fol', 'None')}")
        print("-" * 20)
