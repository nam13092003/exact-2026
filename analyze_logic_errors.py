import json
from collections import Counter

def analyze_errors(filepath):
    try:
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
            
        rows = data.get('rows', [])
        errors = [r for r in rows if not r.get('ok', True)]
        corrects = [r for r in rows if r.get('ok', True)]
        
        print("=== OVERALL METRICS ===")
        print(f"Total Questions: {len(rows)}")
        print(f"Total Errors: {len(errors)} ({(len(errors)/len(rows))*100:.1f}%)")
        print(f"Total Correct: {len(corrects)} ({(len(corrects)/len(rows))*100:.1f}%)")
        
        print("\n=== ERRORS BY QUESTION TYPE ===")
        qtypes_err = Counter(r.get('question_type') for r in errors)
        qtypes_all = Counter(r.get('question_type') for r in rows)
        for qt, count in qtypes_err.most_common():
            total_qt = qtypes_all[qt]
            print(f"- {qt}: {count}/{total_qt} failed ({(count/total_qt)*100:.1f}%)")
            
        print("\n=== ERRORS BY PREDICTION PATTERN ===")
        patterns = Counter(f"Gold: {r.get('gold')} -> Pred: {r.get('pred')}" for r in errors)
        for pat, count in patterns.most_common(10):
            print(f"- {pat}: {count}")

        print("\n=== AVG CONFIDENCE ===")
        if errors:
            avg_conf_err = sum(r.get('confidence', 0) for r in errors) / len(errors)
            print(f"- Incorrect: {avg_conf_err:.3f}")
        if corrects:
            avg_conf_corr = sum(r.get('confidence', 0) for r in corrects) / len(corrects)
            print(f"- Correct: {avg_conf_corr:.3f}")
            
    except Exception as e:
        print(f"Error analyzing JSON: {e}")

if __name__ == '__main__':
    analyze_errors('debug_logic_eval_full.json')
