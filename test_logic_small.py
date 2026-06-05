import json
from pathlib import Path
from agents.pipeline import ExactPipeline
from eval.p1_evaluator import eval_logic

def main():
    logic_kb = "data/Logic_Based_Educational_Queries.json"
    pipe = ExactPipeline(logic_kb_path=logic_kb)
    # Run only 20 records for a quick test
    res = eval_logic(logic_kb, pipe, max_records=20)
    with open("debug_logic_small_test.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"Tested 20 records. Total questions: {res['total']}, Correct: {res['correct']} ({res['p1']*100:.1f}%)")

if __name__ == "__main__":
    main()
