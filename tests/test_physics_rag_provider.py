import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.physics.Solution.rag_provider import RAGSolutionProvider


class FakeQdrantClient:
    def __init__(self) -> None:
        self.created = []
        self.uploads = []
        self.queries = []

    def collection_exists(self, collection_name):
        return False

    def get_embedding_size(self, model_name):
        assert model_name == "test-model"
        return 3

    def create_collection(self, **kwargs):
        self.created.append(kwargs)

    def upload_collection(self, **kwargs):
        self.uploads.append(kwargs)

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(
            points=[SimpleNamespace(payload={"item": {"question": "matched"}})]
        )


class RAGSolutionProviderTest(unittest.TestCase):
    def test_retrieve_indexes_and_queries_qdrant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base = Path(temp_dir) / "physics.json"
            knowledge_base.write_text(
                json.dumps(
                    [
                        {"question": "first question", "answer": "1"},
                        {"question": "second question", "answer": "2"},
                    ]
                ),
                encoding="utf-8",
            )
            client = FakeQdrantClient()
            provider = RAGSolutionProvider(
                llm_provider=None,
                kb_path=knowledge_base,
                top_k=1,
                qdrant_client=client,
                collection_name="physics",
                embedding_model="test-model",
            )

            self.assertEqual(provider.retrieve("find a match"), [{"question": "matched"}])
            self.assertEqual(len(client.created), 1)
            self.assertEqual(len(client.uploads), 1)
            self.assertEqual(len(client.queries), 1)
            self.assertTrue(client.uploads[0]["collection_name"].startswith("physics_"))
            self.assertEqual(
                client.queries[0]["collection_name"],
                client.uploads[0]["collection_name"],
            )
            self.assertEqual(client.queries[0]["limit"], 1)

            provider.retrieve("find it again")
            self.assertEqual(len(client.uploads), 1)
            self.assertEqual(len(client.queries), 2)

    def test_retrieve_does_not_create_collection_for_empty_kb(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base = Path(temp_dir) / "physics.json"
            knowledge_base.write_text("[]", encoding="utf-8")
            client = FakeQdrantClient()
            provider = RAGSolutionProvider(
                llm_provider=None,
                kb_path=knowledge_base,
                qdrant_client=client,
                embedding_model="test-model",
            )

            self.assertEqual(provider.retrieve("anything"), [])
            self.assertEqual(client.created, [])
            self.assertEqual(client.uploads, [])
            self.assertEqual(client.queries, [])


if __name__ == "__main__":
    unittest.main()
