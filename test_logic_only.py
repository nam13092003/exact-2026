import json
from pathlib import Path
from agents.pipeline import ExactPipeline
from eval.p1_evaluator import eval_logic

def main():
    logic_kb = "data/Logic_Based_Educational_Queries.json"
    pipe = ExactPipeline(logic_kb_path=logic_kb)
    res = eval_logic(logic_kb, pipe)
    with open("debug_logic_eval_full.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print("Done. Wrote debug_logic_eval_full.json")

if __name__ == "__main__":
    main()
