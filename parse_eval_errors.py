import json

try:
    with open('debug_logic_eval_full.json', encoding='utf-8') as f:
        data = json.load(f)
    
    rows = data.get('rows', [])
    errors = [r for r in rows if not r.get('ok', True)]
    
    print(f"Total rows: {len(rows)}")
    print(f"Total errors: {len(errors)}")
    
    meta_logic_errs = [r for r in errors if r.get('question_type') == 'MetaLogic']
    print(f"MetaLogic failures: {len(meta_logic_errs)}")
    
    print("\nFirst 3 MetaLogic failures:")
    for err in meta_logic_errs[:3]:
        print(json.dumps(err, indent=2))
        
    print("\nOther failures (first 3):")
    other_errs = [r for r in errors if r.get('question_type') != 'MetaLogic']
    for err in other_errs[:3]:
        print(json.dumps(err, indent=2))

except Exception as e:
    print(f"Error: {e}")
