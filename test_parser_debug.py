import json
from dotenv import load_dotenv
load_dotenv()
from agents.logic_agent import LogicNLParserAgent

def main():
    parser = LogicNLParserAgent()
    premises_nl = [
        "If a student completes the core curriculum and passes the science assessment, they qualify for advanced courses.",
        "If a student qualifies for advanced courses and completes the research methodology seminar, they are eligible for the international exchange program.",
        "Sophia has completed the core curriculum.",
        "Sophia has passed the science assessment.",
        "Sophia has completed the research methodology seminar."
    ]
    question = "Based on the above premises, which is the strongest conclusion?"
    
    print("Testing parse_with_llm...")
    parsed = parser.parse_with_llm(premises_nl, question, fewshot_examples=[])
    print("Parsed result:")
    print(json.dumps(parsed, indent=2) if parsed else "None")

if __name__ == "__main__":
    main()
