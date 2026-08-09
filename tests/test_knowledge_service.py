import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


os.environ.setdefault("MAC_AGENT_TOKEN", "test-token")

from app.api.audio_lab import router as audio_lab_router
from fastapi import HTTPException

from app.api.knowledge import delete_document as delete_document_endpoint
from app.api.knowledge import router as knowledge_router
from app.api.openai_knowledge import (
    ChatCompletionRequest,
    knowledge_chat_completion,
    list_knowledge_models,
    router as openai_knowledge_router,
)
from app.config import settings
from app.services import knowledge_service


class DocumentPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.previous_documents_root = settings.documents_root
        settings.documents_root = str(self.root)

    def tearDown(self) -> None:
        settings.documents_root = self.previous_documents_root
        self.temporary_directory.cleanup()

    def test_accepts_relative_path_inside_documents_root(self) -> None:
        document = self.root / "notes.md"
        document.write_text("hello", encoding="utf-8")

        self.assertEqual(
            knowledge_service.resolve_document_path("notes.md"),
            document,
        )

    def test_rejects_path_outside_documents_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "DOCUMENTS_ROOT"):
            knowledge_service.resolve_document_path("../secret.txt")

    def test_rejects_symlink_escaping_documents_root(self) -> None:
        outside = self.root.parent / "outside-document.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(outside)

        try:
            with self.assertRaisesRegex(ValueError, "DOCUMENTS_ROOT"):
                knowledge_service.resolve_document_path(str(link))
        finally:
            outside.unlink()


class KnowledgeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.document = self.root / "document.txt"
        self.document.write_text("A generic knowledge document.", encoding="utf-8")
        self.previous_documents_root = settings.documents_root
        settings.documents_root = str(self.root)

    async def asyncTearDown(self) -> None:
        settings.documents_root = self.previous_documents_root
        self.temporary_directory.cleanup()

    async def test_registers_generic_document(self) -> None:
        saved = {
            "document_id": "doc-1",
            "index_status": "not_indexed",
        }

        with patch.object(
            knowledge_service.knowledge_state,
            "register_document",
            AsyncMock(return_value=saved),
        ) as register, patch.object(
            knowledge_service.knowledge_state,
            "get_document",
            AsyncMock(return_value=None),
        ):
            result = await knowledge_service.register_document(
                path="document.txt",
                document_id="doc-1",
                source_type="manual",
                project="docs",
            )

        self.assertEqual(result, saved)
        register.assert_awaited_once_with(
            document_id="doc-1",
            text_path=str(self.document),
            source_type="manual",
            project="docs",
            source_filename="document.txt",
        )

    async def test_indexes_generic_document_from_documents_root(self) -> None:
        record = {
            "document_id": "doc-1",
            "task_id": None,
            "text_path": str(self.document),
            "source_type": "document",
            "project": "document-lab",
            "source_filename": "document.txt",
        }

        with (
            patch.object(
                knowledge_service,
                "register_completed_transcriptions",
                AsyncMock(return_value=0),
            ),
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=record),
            ),
            patch.object(
                knowledge_service.knowledge_state,
                "set_status",
                AsyncMock(),
            ) as set_status,
            patch.object(
                knowledge_service.litellm,
                "embeddings",
                AsyncMock(return_value=[[0.1, 0.2]]),
            ),
            patch.object(
                knowledge_service.qdrant,
                "ensure_collection",
                AsyncMock(),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ),
            patch.object(
                knowledge_service.qdrant,
                "upsert_points",
                AsyncMock(),
            ) as upsert,
        ):
            result = await knowledge_service.index_document("doc-1")

        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["chunk_count"], 1)
        self.assertEqual(upsert.await_args.args[0][0]["payload"]["task_id"], None)
        self.assertEqual(set_status.await_count, 2)

    async def test_deletes_generic_document_without_source_file_access(self) -> None:
        record = {
            "document_id": "doc-1",
            "task_id": None,
            "text_path": str(self.document),
            "source_type": "document",
            "project": "document-lab",
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=record),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ) as delete_vectors,
            patch.object(
                knowledge_service.knowledge_state,
                "set_status",
                AsyncMock(),
            ) as set_status,
        ):
            result = await knowledge_service.delete_document("doc-1")

        self.assertTrue(self.document.exists())
        delete_vectors.assert_awaited_once_with("doc-1")
        set_status.assert_awaited_once_with(
            "doc-1",
            "deleted",
            chunk_count=0,
            error=None,
        )
        self.assertEqual(
            result,
            {
                "document_id": "doc-1",
                "index_deleted": True,
                "status": "deleted",
            },
        )

    async def test_delete_unknown_document_fails_before_qdrant(self) -> None:
        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=None),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ) as delete_vectors,
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                await knowledge_service.delete_document("missing")

        delete_vectors.assert_not_awaited()

    async def test_qdrant_failure_does_not_mark_document_deleted(self) -> None:
        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value={"document_id": "doc-1"}),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(side_effect=RuntimeError("Qdrant unavailable")),
            ),
            patch.object(
                knowledge_service.knowledge_state,
                "set_status",
                AsyncMock(),
            ) as set_status,
        ):
            with self.assertRaisesRegex(RuntimeError, "Qdrant unavailable"):
                await knowledge_service.delete_document("doc-1")

        set_status.assert_not_awaited()

    async def test_delete_endpoint_returns_404_for_unknown_document(self) -> None:
        with patch.object(
            knowledge_service,
            "delete_document",
            AsyncMock(side_effect=ValueError("Knowledge document not found")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await delete_document_endpoint("missing")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail,
            "Knowledge document not found",
        )


class EndpointCompatibilityTests(unittest.TestCase):
    def test_generic_document_routes_are_exposed(self) -> None:
        routes = {
            (route.path, method)
            for route in knowledge_router.routes
            for method in route.methods
        }
        expected = {
            ("/knowledge/documents", "POST"),
            ("/knowledge/documents/{document_id}", "GET"),
            ("/knowledge/documents/{document_id}/status", "GET"),
            ("/knowledge/documents/{document_id}/index", "POST"),
            ("/knowledge/documents/{document_id}/reindex", "POST"),
            ("/knowledge/documents/{document_id}/index", "DELETE"),
            ("/knowledge/documents/{document_id}", "DELETE"),
        }
        self.assertTrue(expected.issubset(routes))

    def test_openai_compatible_routes_are_exposed(self) -> None:
        routes = {
            (route.path, method)
            for route in openai_knowledge_router.routes
            for method in route.methods
        }
        self.assertIn(("/v1/models", "GET"), routes)
        self.assertIn(("/v1/chat/completions", "POST"), routes)

    def test_audio_lab_index_routes_remain_exposed(self) -> None:
        routes = {
            (route.path, method)
            for route in audio_lab_router.routes
            for method in route.methods
        }
        expected = {
            ("/audio-lab/tasks", "GET"),
            ("/audio-lab/tasks/{task_id}/index", "POST"),
            ("/audio-lab/tasks/{task_id}/reindex", "POST"),
            ("/audio-lab/tasks/{task_id}/index", "DELETE"),
        }
        self.assertTrue(expected.issubset(routes))


class OpenAIKnowledgeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_models_exposes_only_knowledge_model(self) -> None:
        result = await list_knowledge_models()

        self.assertEqual(result["data"][0]["id"], "homelab-knowledge")

    async def test_chat_maps_history_and_sources_to_openai_response(self) -> None:
        request = ChatCompletionRequest(
            model="homelab-knowledge",
            messages=[
                {"role": "user", "content": "Перше питання"},
                {"role": "assistant", "content": "Перша відповідь"},
                {"role": "user", "content": "Уточни відповідь"},
            ],
        )
        result = {
            "answer": "Відповідь із бази.",
            "sources": [
                {
                    "number": 1,
                    "source_filename": "book.pdf",
                    "score": 0.91,
                }
            ],
            "usage": {"total_tokens": 10},
        }

        with patch.object(
            knowledge_service,
            "chat_with_knowledge",
            AsyncMock(return_value=result),
        ) as chat:
            response = await knowledge_chat_completion(request)

        self.assertEqual(response["object"], "chat.completion")
        content = response["choices"][0]["message"]["content"]
        self.assertIn("Відповідь із бази.", content)
        self.assertIn("[1] book.pdf", content)
        chat.assert_awaited_once()
        self.assertEqual(chat.await_args.args[0], "Уточни відповідь")
        self.assertEqual(
            len(chat.await_args.kwargs["conversation_messages"]),
            3,
        )

if __name__ == "__main__":
    unittest.main()
