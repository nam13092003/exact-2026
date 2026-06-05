import json
from dotenv import load_dotenv
load_dotenv()
from agents.pipeline import ExactPipeline

def main():
    pipe = ExactPipeline()
    premises_nl = [
        "If a student completes the core curriculum and passes the science assessment, they qualify for advanced courses.",
        "If a student qualifies for advanced courses and completes the research methodology seminar, they are eligible for the international exchange program.",
        "Sophia has completed the core curriculum.",
        "Sophia has passed the science assessment.",
        "Sophia has completed the research methodology seminar."
    ]
    question = "Based on the above premises, which is the strongest conclusion?\nA. Sophia qualifies for the university scholarship\nB. Sophia needs a faculty recommendation to qualify for the scholarship\nC. Sophia is eligible for the international program\nD. Sophia needs to pass the language proficiency exam to get an honors diploma"
    
    print("Testing pipeline on Sophia...")
    kb, parsed = pipe.logic.parser.build_kb(premises_nl, question, [])
    
    # Run closure manually to see what it derives
    kb.closure()
    print("Derived Facts:")
    for a in kb.facts:
        if a.truth:
            print(f" - {a.label()}")
            
    # Now check overlaps just like best_choice does
    from agents.logic_agent import split_choices, tokenize, atom_words
    choices = split_choices(question)
    positive_atoms = [a for a in kb.facts if a.truth]
    print("\nOverlap Scores:")
    for label, text in choices.items():
        tw = tokenize(text)
        print(f"Choice {label}: {tw}")
        for atom in positive_atoms:
            aw = atom_words(atom)
            if not aw: continue
            overlap = len(tw & aw) / max(1, len(tw | aw))
            if overlap > 0.1:
                print(f"  vs {atom.label()} (aw={aw}): overlap={overlap:.3f}")
    
    pred, atom, conf = pipe.logic.reasoner.best_choice(kb, question, parsed)
    print(f"\nPred: {pred}")
    print(f"Conf: {conf}")
    print(f"FOL: {atom.label() if atom else None}")

if __name__ == "__main__":
    main()
