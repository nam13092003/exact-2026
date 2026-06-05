from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, Literal

from dotenv import load_dotenv

load_dotenv()

from agents.llm_client import VLLMClient
from agents.logic_agent import LogicAgent
from agents.physics_agent import PhysicsAgent
from agents.router import RouterAgent

# import langsmith + langgraph
try:
    from langgraph.graph import StateGraph, START, END
except Exception:  # allow running without langgraph installed
    StateGraph = START = END = None

try:
    from langsmith import traceable
except Exception:

    def traceable(*args, **kwargs):
        def deco(fn):
            return fn

        return deco


RouteType = Literal["logic", "physics"]


class ExactState(TypedDict, total=False):
    payload: Dict[str, Any]
    question: str
    route: RouteType
    result: Dict[str, Any]


class ExactPipeline:
    def __init__(
        self,
        physics_kb_path: Optional[str] = None,
        logic_kb_path: Optional[str] = None,
        use_rag: bool = True,
    ):
        self.llm = VLLMClient()
        self.router = RouterAgent()
        self.use_rag = use_rag

        self.logic = LogicAgent(self.llm, rag_path=logic_kb_path)
        self.physics = PhysicsAgent(kb_path=physics_kb_path, llm=self.llm)

        self.graph = self._build_graph() if StateGraph is not None else None

    # -------------------------
    # LangGraph nodes
    # -------------------------

    @traceable(name="extract_question")
    def _extract_question_node(self, state: ExactState) -> Dict[str, Any]:
        payload = state["payload"]

        q = payload.get("question")

        if isinstance(q, list):
            raise ValueError(
                "Payload contains a list of questions. "
                "Use predict_record or explode before calling predict."
            )

        question = str(q or "")

        return {
            "question": question,
        }

    @traceable(name="route_question")
    def _route_node(self, state: ExactState) -> Dict[str, Any]:
        payload = state["payload"]

        route = self.router.classify(payload)

        if route not in ("logic", "physics"):
            raise ValueError(f"Unknown route from router: {route}")

        return {
            "route": route,
            "confidence": 93,
        }

    def _route_to_agent(self, state: ExactState) -> str:
        route = state["route"]

        if route == "logic":
            return "solve_logic"

        return "solve_physics"

    @traceable(name="solve_logic")
    def _solve_logic_node(self, state: ExactState) -> Dict[str, Any]:
        payload = state["payload"]
        question = state["question"]

        premises_nl = (
            payload.get("premises-NL")
            or payload.get("premises_nl")
            or payload.get("premises")
            or []
        )

        # Tránh bug list("abc") -> ["a", "b", "c"]
        if isinstance(premises_nl, str):
            premises_nl = [premises_nl]
        else:
            premises_nl = list(premises_nl)

        premises_fol = (
            payload.get("premises-FOL")
            or payload.get("premises_fol")
        )

        res = self.logic.solve(
            question=question,
            premises_nl=premises_nl,
            premises_fol=premises_fol,
            exclude_record_index=payload.get("__record_index"),
            exclude_idx=payload.get("idx"),
            use_rag=self.use_rag,
        )

        res["type"] = "logic"

        return {
            "result": res,
        }

    @traceable(name="solve_physics")
    def _solve_physics_node(self, state: ExactState) -> Dict[str, Any]:
        payload = state["payload"]
        question = state["question"]

        res = self.physics.solve(
            question=question,
            exclude_id=payload.get("id"),
            exclude_record_index=payload.get("__record_index"),
            use_rag=self.use_rag,
        )

        res["type"] = "physics"

        return {
            "result": res,
        }

    # -------------------------
    # Build graph
    # -------------------------

    def _build_graph(self):
        if StateGraph is None:
            return None

        graph = StateGraph(ExactState)

        graph.add_node("extract_question", self._extract_question_node)
        graph.add_node("route", self._route_node)
        graph.add_node("solve_logic", self._solve_logic_node)
        graph.add_node("solve_physics", self._solve_physics_node)

        graph.add_edge(START, "extract_question")
        graph.add_edge("extract_question", "route")

        graph.add_conditional_edges(
            "route",
            self._route_to_agent,
            {
                "solve_logic": "solve_logic",
                "solve_physics": "solve_physics",
            },
        )

        graph.add_edge("solve_logic", END)
        graph.add_edge("solve_physics", END)

        return graph.compile()

    # -------------------------
    # Public API
    # -------------------------

    def predict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.graph is None:
            question = str(payload.get("question") or "")
            route = self.router.classify(payload)

            if route == "logic":
                premises_nl = (
                    payload.get("premises-NL")
                    or payload.get("premises_nl")
                    or payload.get("premises")
                    or []
                )

                if isinstance(premises_nl, str):
                    premises_nl = [premises_nl]
                else:
                    premises_nl = list(premises_nl)

                premises_fol = (
                    payload.get("premises-FOL")
                    or payload.get("premises_fol")
                )

                res = self.logic.solve(
                    question=question,
                    premises_nl=premises_nl,
                    premises_fol=premises_fol,
                    exclude_record_index=payload.get("__record_index"),
                    exclude_idx=payload.get("idx"),
                    question_index=payload.get("__question_index"),
                    use_rag=self.use_rag,
                )
                res["type"] = "logic"
                return res

            res = self.physics.solve(
                question=question,
                exclude_id=payload.get("id"),
                exclude_record_index=payload.get("__record_index"),
                use_rag=self.use_rag,
            )
            res["type"] = "physics"
            return res

        final_state = self.graph.invoke(
            {"payload": payload},
            config={
                "run_name": "exact_pipeline",
                "tags": ["exact", "langgraph", "rag-fewshot"],
                "metadata": {
                    "pipeline": "router-logic-physics-rag-fewshot",
                    "use_rag": self.use_rag,
                },
            },
        )

        return final_state["result"]

    def predict_record(self, record: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(record.get("questions"), list):
            outputs = []

            for i, q in enumerate(record["questions"]):
                payload = dict(record)
                payload["question"] = q
                payload["__question_index"] = i
                payload.pop("questions", None)

                out = self.predict(payload)
                out["question_index"] = i
                outputs.append(out)

            return outputs

        return [self.predict(record)]