"""Retrieval-augmented provider for SymPy-compatible physics formulas."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from agents.llm import LLMClientBase

from .llm_provider import LLMSolutionProvider


class RAGSolutionProvider(LLMSolutionProvider):
    """Generate formulas after retrieving similar solved physics examples."""

    DEFAULT_KB_PATH = Path(__file__).resolve().parents[3] / "data" / "Physics_Problems_Text_Only_removeQA.json"
    DEFAULT_COLLECTION = "exact_physics_rag"
    DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(
        self,
        llm_provider: LLMClientBase,
        kb_path: str | Path | None = None,
        top_k: int = 2,
        qdrant_client: QdrantClient | None = None,
        collection_name: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        """Configure the LLM, vector store, knowledge base, and result count."""
        super().__init__(llm_provider)
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        self.kb_path = Path(kb_path) if kb_path else self.DEFAULT_KB_PATH
        self.top_k = top_k
        self.collection_name = collection_name or os.getenv(
            "QDRANT_COLLECTION",
            self.DEFAULT_COLLECTION,
        )
        self.embedding_model = embedding_model or os.getenv(
            "QDRANT_EMBEDDING_MODEL",
            self.DEFAULT_EMBEDDING_MODEL,
        )
        self._qdrant = qdrant_client
        self._documents: list[dict[str, Any]] | None = None
        self._indexed = False

    def _load_documents(self) -> list[dict[str, Any]]:
        """Load usable physics examples from the configured JSON knowledge base."""
        if self._documents is not None:
            return self._documents
        try:
            with self.kb_path.open("r", encoding="utf-8") as source:
                data = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not load physics knowledge base: {self.kb_path}") from exc
        if not isinstance(data, list):
            raise ValueError("Physics knowledge base must contain a JSON list.")
        self._documents = [
            item
            for item in data
            if isinstance(item, dict) and isinstance(item.get("question"), str)
        ]
        return self._documents

    def _get_qdrant_client(self) -> QdrantClient:
        """Return the configured Qdrant client, creating a local one by default."""
        if self._qdrant is not None:
            return self._qdrant
        url = os.getenv("QDRANT_URL", "").strip()
        api_key = os.getenv("QDRANT_API_KEY", "").strip() or None
        self._qdrant = (
            QdrantClient(url=url, api_key=api_key)
            if url
            else QdrantClient(":memory:")
        )
        return self._qdrant

    def _resolved_collection_name(self, documents: list[dict[str, Any]]) -> str:
        """Namespace the collection by corpus and embedding model revisions."""
        fingerprint_source = json.dumps(
            {"model": self.embedding_model, "documents": documents},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hashlib.sha256(fingerprint_source).hexdigest()[:12]
        return f"{self.collection_name}_{fingerprint}"

    def _ensure_index(self) -> tuple[QdrantClient, str]:
        """Create and populate the Qdrant collection once per provider instance."""
        documents = self._load_documents()
        client = self._get_qdrant_client()
        collection_name = self._resolved_collection_name(documents)
        if self._indexed or not documents:
            return client, collection_name

        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=client.get_embedding_size(self.embedding_model),
                    distance=models.Distance.COSINE,
                ),
            )

        client.upload_collection(
            collection_name=collection_name,
            vectors=[
                models.Document(text=item["question"], model=self.embedding_model)
                for item in documents
            ],
            payload=[{"document": item["question"], "item": item} for item in documents],
            ids=list(range(len(documents))),
        )
        self._indexed = True
        return client, collection_name

    def retrieve(self, question: str) -> list[dict[str, Any]]:
        """Return the top-k semantically similar examples from Qdrant."""
        documents = self._load_documents()
        if not documents:
            return []
        client, collection_name = self._ensure_index()
        points = client.query_points(
            collection_name=collection_name,
            query=models.Document(text=question, model=self.embedding_model),
            limit=min(self.top_k, len(documents)),
            with_payload=True,
        ).points
        return [
            point.payload["item"]
            for point in points
            if point.payload and isinstance(point.payload.get("item"), dict)
        ]

    def _compact_example(self, item: dict[str, Any]) -> dict[str, Any]:
        """Convert a retrieved solved problem into a small formula/strategy hint."""
        return self._compact_rag_example(item)

    def _deterministic_solution(self, semantic_output: dict[str, Any]) -> dict[str, Any] | None:
        """Use shared deterministic formulas before falling back to retrieved prompts."""
        return super()._deterministic_solution(semantic_output)

    def get_solution(self, question: str, semantic_output: dict[str, Any]) -> dict[str, Any]:
        """Request a solution with parsed data, deterministic hints, retrieved examples, and final verification."""
        deterministic = self._deterministic_solution(semantic_output)
        examples = [self._compact_example(item) for item in self.retrieve(question)]
        prompt = self._build_prompt(
            semantic_output,
            retrieved_examples=examples,
            deterministic_solution=deterministic,
        )
        solution_draft = self._request_solution(
            prompt,
            semantic_output,
            deterministic_fallback=deterministic,
        )
        return self._finalize_solution(question, semantic_output, solution_draft)
