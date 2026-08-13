import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError


os.environ.setdefault("MAC_AGENT_TOKEN", "test-token")

from app.api.audio_lab import audio_tasks
from app.api.audio_lab import router as audio_lab_router
from fastapi import HTTPException

from app.api.knowledge import delete_document as delete_document_endpoint
from app.api.knowledge import list_documents as list_documents_endpoint
from app.api.knowledge import router as knowledge_router
from app.api.openai_knowledge import (
    ChatCompletionRequest,
    _answer_with_sources,
    knowledge_chat_completion,
    list_knowledge_models,
    router as openai_knowledge_router,
)
from app.config import settings
from app.models.knowledge import (
    KnowledgeDeleteAllRequest,
    KnowledgePurgeDeletedRequest,
    KnowledgeTranscriptionRegistration,
)
from app.models.task import TaskCreate
from app.models.task import TaskType
from app.providers import qdrant
from app.services import knowledge_service
from app.services import knowledge_state
from app.services import task_service
from app.storage.database import initialize_database


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


class AudioTranscriptionRegistrationTests(
    unittest.IsolatedAsyncioTestCase,
):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.audio_root = self.root / "audio"
        self.documents_root = self.root / "documents"
        self.audio_root.mkdir()
        self.documents_root.mkdir()
        self.session_dir = self.audio_root / "sessions" / "session-1"
        self.session_dir.mkdir(parents=True)
        self.transcript = self.session_dir / "lesson.txt"
        self.transcript.write_text("German lesson transcript.", encoding="utf-8")
        self.outside = self.root / "outside.txt"
        self.outside.write_text("outside", encoding="utf-8")
        self.previous_audio_root = settings.audio_root
        self.previous_documents_root = settings.documents_root
        self.previous_database_path = settings.database_path
        settings.audio_root = str(self.audio_root)
        settings.documents_root = str(self.documents_root)
        settings.database_path = str(self.root / "knowledge.db")
        await initialize_database()

    async def asyncTearDown(self) -> None:
        settings.audio_root = self.previous_audio_root
        settings.documents_root = self.previous_documents_root
        settings.database_path = self.previous_database_path
        self.temporary_directory.cleanup()

    async def test_registers_relative_audio_session_transcript(self) -> None:
        record = await knowledge_service.register_transcription(
            document_id="audio-session-1",
            text_path="sessions/session-1/lesson.txt",
            source_filename="German Lesson — 11.08.2026.txt",
        )

        self.assertEqual(record["text_path"], str(self.transcript))
        self.assertEqual(record["source_type"], "transcription")
        self.assertEqual(record["project"], "audio-lab")
        self.assertEqual(
            record["source_filename"],
            "German Lesson — 11.08.2026.txt",
        )

    def test_rejects_absolute_audio_transcript_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be relative"):
            knowledge_service.resolve_audio_transcription_path(
                str(self.transcript)
            )

    def test_rejects_parent_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside AUDIO_ROOT"):
            knowledge_service.resolve_audio_transcription_path("../outside.txt")

    def test_rejects_symlink_escape(self) -> None:
        link = self.audio_root / "sessions" / "outside-link.txt"
        link.symlink_to(self.outside)

        with self.assertRaisesRegex(ValueError, "outside AUDIO_ROOT"):
            knowledge_service.resolve_audio_transcription_path(
                "sessions/outside-link.txt"
            )

    def test_rejects_missing_audio_transcript(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "not found"):
            knowledge_service.resolve_audio_transcription_path(
                "sessions/session-1/missing.txt"
            )

    def test_rejects_non_file_audio_transcript(self) -> None:
        with self.assertRaisesRegex(ValueError, "must point to a file"):
            knowledge_service.resolve_audio_transcription_path("sessions")

    def test_registration_model_rejects_client_root_or_metadata(self) -> None:
        with self.assertRaises(ValidationError):
            KnowledgeTranscriptionRegistration(
                document_id="audio-session-1",
                text_path="sessions/session-1/lesson.txt",
                source_filename="Lesson.txt",
                root="/remote/Audio",
            )

        with self.assertRaises(ValidationError):
            KnowledgeTranscriptionRegistration(
                document_id="audio-session-1",
                text_path="sessions/session-1/lesson.txt",
                source_filename="Lesson.txt",
                source_type="document",
            )

    async def test_generic_registration_remains_documents_root_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "DOCUMENTS_ROOT"):
            await knowledge_service.register_document(
                path=str(self.transcript),
                document_id="generic-wrong-root",
            )

    async def test_reregistration_keeps_one_stable_document(self) -> None:
        for filename in ("Lesson one.txt", "Lesson renamed.txt"):
            await knowledge_service.register_transcription(
                document_id="audio-session-1",
                text_path="sessions/session-1/lesson.txt",
                source_filename=filename,
            )

        rows = await knowledge_state.list_documents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["document_id"], "audio-session-1")
        self.assertEqual(rows[0]["source_filename"], "Lesson renamed.txt")

    async def test_indexes_explicit_audio_session_from_audio_root(self) -> None:
        await knowledge_service.register_transcription(
            document_id="audio-session-1",
            text_path="sessions/session-1/lesson.txt",
            source_filename="Lesson.txt",
        )

        with (
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
            result = await knowledge_service.index_document("audio-session-1")

        self.assertEqual(result["status"], "indexed")
        self.assertEqual(
            upsert.await_args.args[0][0]["payload"]["source_type"],
            "transcription",
        )

    async def test_existing_task_transcription_still_indexes_from_audio_root(
        self,
    ) -> None:
        record = {
            "document_id": "task-1",
            "task_id": "task-1",
            "text_path": str(self.transcript),
            "source_type": "transcription",
            "project": "audio-lab",
            "source_filename": "lesson.txt",
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=record),
            ),
            patch.object(
                knowledge_service.knowledge_state,
                "set_status",
                AsyncMock(),
            ),
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
            ),
        ):
            result = await knowledge_service.index_document("task-1")

        self.assertEqual(result["status"], "indexed")

    async def test_delete_knowledge_keeps_session_transcript(self) -> None:
        await knowledge_service.register_transcription(
            document_id="audio-session-1",
            text_path="sessions/session-1/lesson.txt",
            source_filename="Lesson.txt",
        )

        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ):
            await knowledge_service.delete_document("audio-session-1")

        self.assertTrue(self.transcript.exists())
        self.assertIsNone(
            await knowledge_state.get_document("audio-session-1")
        )

        await initialize_database()
        self.assertIsNone(
            await knowledge_state.get_document("audio-session-1")
        )

    async def test_completed_audio_task_does_not_create_knowledge_record(
        self,
    ) -> None:
        task = await task_service.create_task(
            TaskCreate(
                type=TaskType.WHISPER,
                payload={"original_filename": "lesson.webm"},
            )
        )
        claimed = await task_service.claim_next_task("whisper")
        self.assertIsNotNone(claimed)
        await task_service.complete_task(
            task.id,
            {"output_files": [str(self.transcript)]},
        )

        await audio_tasks(limit=50)

        self.assertIsNone(await knowledge_state.get_document(task.id))
        self.assertEqual(
            (await knowledge_service.list_knowledge_documents())["total"],
            0,
        )

    async def test_local_document_artifact_does_not_create_knowledge_record(
        self,
    ) -> None:
        document = self.documents_root / "imported.txt"
        document.write_text(
            "Imported locally, but not ingested.",
            encoding="utf-8",
        )

        result = await list_documents_endpoint(limit=50, offset=0)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["documents"], [])

    async def test_explicit_registration_can_recreate_deleted_record(
        self,
    ) -> None:
        await knowledge_service.register_transcription(
            document_id="audio-session-1",
            text_path="sessions/session-1/lesson.txt",
            source_filename="Lesson.txt",
        )
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ):
            await knowledge_service.delete_document("audio-session-1")

        recreated = await knowledge_service.register_transcription(
            document_id="audio-session-1",
            text_path="sessions/session-1/lesson.txt",
            source_filename="Lesson.txt",
        )

        self.assertEqual(recreated["index_status"], "not_indexed")
        self.assertTrue(self.transcript.exists())


class QdrantGroupingTests(unittest.TestCase):
    def test_flattens_one_hit_per_document_before_second_hits(self) -> None:
        groups = [
            {"id": "book", "hits": [{"id": "book-1"}, {"id": "book-2"}]},
            {"id": "audio-1", "hits": [{"id": "audio-1"}]},
            {"id": "audio-2", "hits": [{"id": "audio-2"}]},
        ]

        points = qdrant.flatten_point_groups(
            groups,
            limit=4,
            group_size=2,
        )

        self.assertEqual(
            [point["id"] for point in points],
            ["book-1", "audio-1", "audio-2", "book-2"],
        )


class KnowledgeStateQueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.previous_database_path = settings.database_path
        settings.database_path = str(self.root / "knowledge.db")
        self.generic_source = self.root / "alpha-notes.txt"
        self.generic_source.write_text("Alpha", encoding="utf-8")
        self.deleted_source = self.root / "deleted-report.txt"
        self.deleted_source.write_text("Deleted", encoding="utf-8")
        self.audio_source = self.root / "audio-transcript.txt"
        self.audio_source.write_text("Audio", encoding="utf-8")
        await initialize_database()
        await knowledge_state.register_document(
            document_id="generic-1",
            text_path=str(self.generic_source),
            source_type="document",
            project="document-lab",
            source_filename="alpha-notes.txt",
        )
        await knowledge_state.register_document(
            document_id="generic-deleted",
            text_path=str(self.deleted_source),
            source_type="document",
            project="archive",
            source_filename="deleted-report.txt",
        )
        await knowledge_state.register_document(
            document_id="audio-1",
            text_path=str(self.audio_source),
            source_type="transcription",
            project="audio-lab",
            source_filename="meeting.wav",
        )
        await knowledge_state.set_status(
            "generic-1",
            "indexed",
            chunk_count=2,
            indexed=True,
        )
        await knowledge_state.set_status(
            "generic-deleted",
            "deleted",
            chunk_count=0,
        )
        await knowledge_state.set_status(
            "audio-1",
            "failed",
            error="Embedding failed",
        )

    async def asyncTearDown(self) -> None:
        settings.database_path = self.previous_database_path
        self.temporary_directory.cleanup()

    async def test_normal_list_excludes_legacy_deleted_records(self) -> None:
        rows, total = await knowledge_state.query_documents(
            limit=50,
            offset=0,
        )

        self.assertEqual(total, 2)
        self.assertEqual(
            {row["document_id"] for row in rows},
            {"generic-1", "audio-1"},
        )

    async def test_pagination_preserves_total_count(self) -> None:
        first_page, total = await knowledge_state.query_documents(
            limit=1,
            offset=0,
        )
        second_page, second_total = await knowledge_state.query_documents(
            limit=1,
            offset=1,
        )

        self.assertEqual(len(first_page), 1)
        self.assertEqual(len(second_page), 1)
        self.assertNotEqual(
            first_page[0]["document_id"],
            second_page[0]["document_id"],
        )
        self.assertEqual(total, 2)
        self.assertEqual(second_total, 2)

    async def test_source_type_filter(self) -> None:
        rows, total = await knowledge_state.query_documents(
            source_type="transcription",
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["document_id"], "audio-1")

    async def test_project_filter(self) -> None:
        rows, total = await knowledge_state.query_documents(
            project="document-lab",
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["document_id"], "generic-1")

    async def test_status_filter_includes_deleted_records(self) -> None:
        rows, total = await knowledge_state.query_documents(
            status="deleted",
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["document_id"], "generic-deleted")

    async def test_active_filter_excludes_deleted_records(self) -> None:
        rows, total = await knowledge_state.query_documents(
            status="active",
        )

        self.assertEqual(total, 2)
        self.assertEqual(
            {row["document_id"] for row in rows},
            {"generic-1", "audio-1"},
        )

    async def test_query_filters_by_source_filename(self) -> None:
        rows, total = await knowledge_state.query_documents(
            query="ALPHA",
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["source_filename"], "alpha-notes.txt")

    async def test_delete_knowledge_removes_row_and_keeps_source(self) -> None:
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ) as delete_vectors:
            result = await knowledge_service.delete_document("generic-1")

        delete_vectors.assert_awaited_once_with("generic-1")
        self.assertEqual(result["status"], "removed")
        self.assertIsNone(await knowledge_state.get_document("generic-1"))
        self.assertTrue(self.generic_source.exists())

        await initialize_database()
        rows, total = await knowledge_state.query_documents(
            limit=50,
            offset=0,
        )
        self.assertEqual(total, 1)
        self.assertNotIn(
            "generic-1",
            {row["document_id"] for row in rows},
        )

    async def test_delete_all_removes_rows_and_keeps_source_files(self) -> None:
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ):
            result = await knowledge_service.delete_all_documents()

        rows = await knowledge_state.list_documents()
        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["succeeded"], 3)
        self.assertEqual(rows, [])
        self.assertTrue(self.generic_source.exists())
        self.assertTrue(self.deleted_source.exists())
        self.assertTrue(self.audio_source.exists())

    async def test_delete_all_reports_partial_qdrant_failure(self) -> None:
        async def delete_vectors(document_id: str) -> None:
            if document_id == "generic-1":
                raise RuntimeError("Qdrant unavailable")

        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(side_effect=delete_vectors),
        ):
            result = await knowledge_service.delete_all_documents()

        failed = [
            item
            for item in result["results"]
            if item["document_id"] == "generic-1"
        ][0]
        record = await knowledge_state.get_document("generic-1")
        self.assertEqual(result["requested"], 3)
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Qdrant unavailable", failed["error"])
        self.assertEqual(record["index_status"], "indexed")
        self.assertIsNone(await knowledge_state.get_document("audio-1"))
        self.assertIsNone(
            await knowledge_state.get_document("generic-deleted")
        )
        self.assertTrue(self.generic_source.exists())
        self.assertTrue(self.deleted_source.exists())
        self.assertTrue(self.audio_source.exists())

    async def test_purge_only_deleted_removes_row_without_side_effects(
        self,
    ) -> None:
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ) as delete_vectors:
            result = await knowledge_service.purge_document_registry(
                "generic-deleted"
            )

        self.assertEqual(result["status"], "purged")
        self.assertIsNone(
            await knowledge_state.get_document("generic-deleted")
        )
        delete_vectors.assert_not_awaited()
        self.assertTrue(self.deleted_source.exists())

    async def test_purge_rejects_non_deleted_record(self) -> None:
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ) as delete_vectors:
            with self.assertRaisesRegex(
                ValueError,
                "index_status=deleted",
            ):
                await knowledge_service.purge_document_registry(
                    "generic-1"
                )

        self.assertIsNotNone(
            await knowledge_state.get_document("generic-1")
        )
        delete_vectors.assert_not_awaited()
        self.assertTrue(self.generic_source.exists())

    async def test_purge_deleted_registry_removes_only_deleted_rows(
        self,
    ) -> None:
        with patch.object(
            knowledge_service.qdrant,
            "delete_document",
            AsyncMock(),
        ) as delete_vectors:
            result = await knowledge_service.purge_deleted_registry()

        rows, total = await knowledge_state.query_documents(
            status="all",
            limit=None,
        )
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(total, 2)
        self.assertEqual(
            {row["document_id"] for row in rows},
            {"generic-1", "audio-1"},
        )
        delete_vectors.assert_not_awaited()
        self.assertTrue(self.deleted_source.exists())


class KnowledgeManagementServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.available_source = self.root / "available.txt"
        self.available_source.write_text("Available", encoding="utf-8")
        self.missing_source = self.root / "missing.txt"

    async def asyncTearDown(self) -> None:
        self.temporary_directory.cleanup()

    def records(self) -> list[dict]:
        return [
            {
                "document_id": "available",
                "task_id": None,
                "source_type": "document",
                "project": "document-lab",
                "source_filename": "available.txt",
                "text_path": str(self.available_source),
                "index_status": "indexed",
                "chunk_count": 1,
                "embedding_model": "configured-model",
                "collection_name": "configured-collection",
                "indexed_at": "2026-08-11T10:00:00+00:00",
                "updated_at": "2026-08-11T10:00:00+00:00",
                "error": None,
            },
            {
                "document_id": "missing",
                "task_id": "audio-task",
                "source_type": "transcription",
                "project": "audio-lab",
                "source_filename": "missing.wav",
                "text_path": str(self.missing_source),
                "index_status": "failed",
                "chunk_count": 0,
                "embedding_model": "configured-model",
                "collection_name": "configured-collection",
                "indexed_at": None,
                "updated_at": "2026-08-11T09:00:00+00:00",
                "error": "Source missing",
            },
        ]

    async def test_list_computes_source_availability_without_paths(self) -> None:
        with patch.object(
            knowledge_service.knowledge_state,
            "query_documents",
            AsyncMock(return_value=(self.records(), 2)),
        ):
            result = await knowledge_service.list_knowledge_documents()

        self.assertEqual(result["total"], 2)
        self.assertTrue(result["documents"][0]["source_available"])
        self.assertFalse(result["documents"][1]["source_available"])
        self.assertNotIn("text_path", result["documents"][0])

    async def test_default_list_requests_active_records(self) -> None:
        with patch.object(
            knowledge_service.knowledge_state,
            "query_documents",
            AsyncMock(return_value=(self.records(), 2)),
        ) as query:
            await knowledge_service.list_knowledge_documents()

        self.assertEqual(query.await_args.kwargs["status"], "active")

    async def test_source_available_filter_has_correct_total(self) -> None:
        with patch.object(
            knowledge_service.knowledge_state,
            "query_documents",
            AsyncMock(return_value=(self.records(), 2)),
        ) as query:
            result = await knowledge_service.list_knowledge_documents(
                source_available=True,
                limit=1,
                offset=0,
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["documents"][0]["document_id"],
            "available",
        )
        self.assertIsNone(query.await_args.kwargs["limit"])

    async def test_source_unavailable_filter_returns_missing_source(
        self,
    ) -> None:
        with patch.object(
            knowledge_service.knowledge_state,
            "query_documents",
            AsyncMock(return_value=(self.records(), 2)),
        ):
            result = await knowledge_service.list_knowledge_documents(
                source_available=False,
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["documents"][0]["document_id"],
            "missing",
        )

    async def test_bulk_index_succeeds_for_multiple_documents(self) -> None:
        with patch.object(
            knowledge_service,
            "index_document",
            AsyncMock(
                side_effect=[
                    {"document_id": "one", "status": "indexed"},
                    {"document_id": "two", "status": "indexed"},
                ]
            ),
        ):
            result = await knowledge_service.bulk_document_operation(
                ["one", "two"],
                "index",
            )

        self.assertEqual(result["requested"], 2)
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(result["failed"], 0)

    async def test_bulk_index_reports_partial_and_unknown_failure(self) -> None:
        async def index(document_id: str) -> dict:
            if document_id == "missing":
                raise ValueError("Knowledge document not found")
            return {"document_id": document_id, "status": "indexed"}

        with patch.object(
            knowledge_service,
            "index_document",
            AsyncMock(side_effect=index),
        ):
            result = await knowledge_service.bulk_document_operation(
                ["known", "missing"],
                "index",
            )

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][1]["status"], "failed")
        self.assertIn("not found", result["results"][1]["error"])

    async def test_bulk_retry_requires_failed_and_available_source(
        self,
    ) -> None:
        documents = {
            "eligible": {
                "document_id": "eligible",
                "index_status": "failed",
                "text_path": str(self.available_source),
            },
            "indexed": {
                "document_id": "indexed",
                "index_status": "indexed",
                "text_path": str(self.available_source),
            },
            "missing": {
                "document_id": "missing",
                "index_status": "failed",
                "text_path": str(self.missing_source),
            },
        }

        async def get_document(document_id: str) -> dict:
            return documents[document_id]

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(side_effect=get_document),
            ),
            patch.object(
                knowledge_service,
                "index_document",
                AsyncMock(
                    return_value={
                        "document_id": "eligible",
                        "status": "indexed",
                    }
                ),
            ) as index,
        ):
            result = await knowledge_service.bulk_document_operation(
                ["eligible", "indexed", "missing"],
                "retry",
            )

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 2)
        index.assert_awaited_once_with("eligible")
        self.assertIn(
            "index_status=failed",
            result["results"][1]["error"],
        )
        self.assertIn(
            "available source",
            result["results"][2]["error"],
        )

    async def test_bulk_delete_index_uses_existing_service(self) -> None:
        with patch.object(
            knowledge_service,
            "delete_document_index",
            AsyncMock(
                return_value={
                    "document_id": "one",
                    "status": "not_indexed",
                }
            ),
        ) as delete_index:
            result = await knowledge_service.bulk_document_operation(
                ["one"],
                "delete-index",
            )

        delete_index.assert_awaited_once_with("one")
        self.assertEqual(result["results"][0]["status"], "not_indexed")

    async def test_bulk_delete_never_deletes_source_file(self) -> None:
        with patch.object(
            knowledge_service,
            "delete_document",
            AsyncMock(
                return_value={
                    "document_id": "one",
                    "status": "removed",
                }
            ),
        ) as delete:
            result = await knowledge_service.bulk_document_operation(
                ["one"],
                "delete",
            )

        delete.assert_awaited_once_with("one")
        self.assertEqual(result["results"][0]["status"], "removed")
        self.assertTrue(self.available_source.exists())

    async def test_bulk_purge_reports_ineligible_record(self) -> None:
        async def purge(document_id: str) -> dict:
            if document_id == "active":
                raise ValueError(
                    "Registry purge requires index_status=deleted"
                )
            return {"document_id": document_id, "status": "purged"}

        with patch.object(
            knowledge_service,
            "purge_document_registry",
            AsyncMock(side_effect=purge),
        ):
            result = await knowledge_service.bulk_document_operation(
                ["deleted", "active"],
                "purge",
            )

        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][0]["status"], "purged")
        self.assertIn(
            "index_status=deleted",
            result["results"][1]["error"],
        )


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

    async def test_reregistration_with_same_path_keeps_index(self) -> None:
        existing = {
            "document_id": "doc-1",
            "task_id": None,
            "text_path": str(self.document),
            "index_status": "indexed",
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=existing),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ) as delete_vectors,
            patch.object(
                knowledge_service.knowledge_state,
                "register_document",
                AsyncMock(return_value=existing),
            ) as register,
        ):
            result = await knowledge_service.register_document(
                path="document.txt",
                document_id="doc-1",
            )

        self.assertEqual(result, existing)
        delete_vectors.assert_not_awaited()
        register.assert_awaited_once()

    async def test_reregistration_with_changed_path_deletes_index(self) -> None:
        replacement = self.root / "replacement.txt"
        replacement.write_text("Replacement document.", encoding="utf-8")
        existing = {
            "document_id": "doc-1",
            "task_id": None,
            "text_path": str(self.document),
            "index_status": "indexed",
        }
        saved = {
            **existing,
            "text_path": str(replacement),
            "index_status": "not_indexed",
            "chunk_count": 0,
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=existing),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ) as delete_vectors,
            patch.object(
                knowledge_service.knowledge_state,
                "register_document",
                AsyncMock(return_value=saved),
            ) as register,
        ):
            result = await knowledge_service.register_document(
                path="replacement.txt",
                document_id="doc-1",
            )

        delete_vectors.assert_awaited_once_with("doc-1")
        register.assert_awaited_once()
        self.assertEqual(result["index_status"], "not_indexed")
        self.assertEqual(result["chunk_count"], 0)
        self.assertTrue(self.document.exists())
        self.assertTrue(replacement.exists())

    async def test_reregistration_qdrant_failure_preserves_record(self) -> None:
        replacement = self.root / "replacement.txt"
        replacement.write_text("Replacement document.", encoding="utf-8")
        existing = {
            "document_id": "doc-1",
            "task_id": None,
            "text_path": str(self.document),
            "index_status": "indexed",
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=existing),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(side_effect=RuntimeError("Qdrant unavailable")),
            ),
            patch.object(
                knowledge_service.knowledge_state,
                "register_document",
                AsyncMock(),
            ) as register,
        ):
            with self.assertRaisesRegex(RuntimeError, "Qdrant unavailable"):
                await knowledge_service.register_document(
                    path="replacement.txt",
                    document_id="doc-1",
                )

        register.assert_not_awaited()
        self.assertTrue(self.document.exists())
        self.assertTrue(replacement.exists())

    async def test_reregistration_does_not_modify_audio_lab_record(self) -> None:
        existing = {
            "document_id": "audio-task-1",
            "task_id": "audio-task-1",
            "text_path": str(self.document),
            "index_status": "indexed",
        }

        with (
            patch.object(
                knowledge_service.knowledge_state,
                "get_document",
                AsyncMock(return_value=existing),
            ),
            patch.object(
                knowledge_service.qdrant,
                "delete_document",
                AsyncMock(),
            ) as delete_vectors,
            patch.object(
                knowledge_service.knowledge_state,
                "register_document",
                AsyncMock(),
            ) as register,
        ):
            with self.assertRaisesRegex(ValueError, "Audio Lab"):
                await knowledge_service.register_document(
                    path="document.txt",
                    document_id="audio-task-1",
                )

        delete_vectors.assert_not_awaited()
        register.assert_not_awaited()

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
                "delete_document",
                AsyncMock(return_value=True),
            ) as delete_registry,
        ):
            result = await knowledge_service.delete_document("doc-1")

        self.assertTrue(self.document.exists())
        delete_vectors.assert_awaited_once_with("doc-1")
        delete_registry.assert_awaited_once_with("doc-1")
        self.assertEqual(
            result,
            {
                "document_id": "doc-1",
                "index_deleted": True,
                "status": "removed",
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
                "delete_document",
                AsyncMock(),
            ) as delete_registry,
        ):
            with self.assertRaisesRegex(RuntimeError, "Qdrant unavailable"):
                await knowledge_service.delete_document("doc-1")

        delete_registry.assert_not_awaited()
        self.assertTrue(self.document.exists())

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

class KnowledgeManagerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        frontend = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "frontend"
            / "knowledge_manager"
        )
        cls.html = (frontend / "index.html").read_text(encoding="utf-8")
        cls.javascript = (frontend / "app.js").read_text(encoding="utf-8")

    def test_deleted_state_is_absent_from_active_ui(self) -> None:
        self.assertNotIn('id="stat-deleted"', self.html)
        self.assertNotIn('option value="deleted"', self.html)
        self.assertNotIn('case "deleted"', self.javascript)

    def test_delete_all_controls_are_absent(self) -> None:
        self.assertNotIn("Delete ALL Knowledge", self.html)
        self.assertNotIn("delete-all", self.javascript)
        self.assertNotIn("DELETE ALL KNOWLEDGE", self.javascript)

    def test_all_status_is_omitted_from_document_query(self) -> None:
        self.assertNotIn("status: elements.status.value", self.javascript)
        self.assertIn(
            'if (elements.status.value !== "all") {',
            self.javascript,
        )
        self.assertIn(
            'params.set("status", elements.status.value);',
            self.javascript,
        )

    def test_initial_load_refreshes_global_statistics(self) -> None:
        self.assertIn(
            "loadDocuments({refreshStats: true}).catch((error) => {",
            self.javascript,
        )

    def test_bulk_actions_refresh_global_statistics(self) -> None:
        self.assertIn(
            "await loadDocuments({refreshStats: true});",
            self.javascript,
        )

    def test_filter_reloads_do_not_refresh_global_statistics(self) -> None:
        self.assertIn("function scheduleFilterReload() {", self.javascript)
        filter_section = self.javascript.split(
            "function scheduleFilterReload() {",
            1,
        )[1].split("elements.selectPage.addEventListener", 1)[0]
        self.assertIn("loadDocuments();", filter_section)
        self.assertNotIn("refreshStats", filter_section)

    def test_document_id_is_not_visible_ui_content(self) -> None:
        self.assertNotIn("Document ID", self.html)
        self.assertNotIn("Filename or document ID", self.html)
        self.assertIn('placeholder="Filename"', self.html)

    def test_source_unavailable_uses_neutral_wording(self) -> None:
        self.assertIn("Not local", self.html)
        self.assertIn('"Not local"', self.javascript)
        self.assertNotIn("✖ Missing", self.javascript)

    def test_source_dependent_row_actions_require_availability(self) -> None:
        self.assertIn(
            'available ? [{operation: "index", label: "Index"}] : []',
            self.javascript,
        )
        self.assertIn(
            'available ? [{operation: "reindex", label: "Reindex"}] : []',
            self.javascript,
        )
        self.assertIn(
            'available ? [{operation: "retry", label: "Retry"}] : []',
            self.javascript,
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
            ("/knowledge/transcriptions", "POST"),
            ("/knowledge/documents", "GET"),
            ("/knowledge/documents/bulk/index", "POST"),
            ("/knowledge/documents/bulk/reindex", "POST"),
            ("/knowledge/documents/bulk/retry", "POST"),
            ("/knowledge/documents/bulk/delete-index", "POST"),
            ("/knowledge/documents/bulk/delete", "POST"),
            ("/knowledge/documents/bulk/purge", "POST"),
            ("/knowledge/documents/delete-all", "POST"),
            ("/knowledge/documents/purge-deleted", "POST"),
            ("/knowledge/documents/{document_id}", "GET"),
            ("/knowledge/documents/{document_id}/status", "GET"),
            ("/knowledge/documents/{document_id}/index", "POST"),
            ("/knowledge/documents/{document_id}/reindex", "POST"),
            ("/knowledge/documents/{document_id}/index", "DELETE"),
            ("/knowledge/documents/{document_id}", "DELETE"),
            ("/knowledge/documents/{document_id}/registry", "DELETE"),
            ("/knowledge/search", "POST"),
            ("/knowledge/chat", "POST"),
        }
        self.assertTrue(expected.issubset(routes))

    def test_bulk_routes_precede_dynamic_document_routes(self) -> None:
        paths = [route.path for route in knowledge_router.routes]
        dynamic_position = paths.index(
            "/knowledge/documents/{document_id}"
        )

        for path in (
            "/knowledge/documents/bulk/index",
            "/knowledge/documents/bulk/reindex",
            "/knowledge/documents/bulk/retry",
            "/knowledge/documents/bulk/delete-index",
            "/knowledge/documents/bulk/delete",
            "/knowledge/documents/bulk/purge",
            "/knowledge/documents/delete-all",
            "/knowledge/documents/purge-deleted",
        ):
            self.assertLess(paths.index(path), dynamic_position)

    def test_delete_all_requires_exact_confirmation(self) -> None:
        with self.assertRaises(ValidationError):
            KnowledgeDeleteAllRequest(confirmation="delete all")

        request = KnowledgeDeleteAllRequest(
            confirmation="DELETE ALL KNOWLEDGE"
        )
        self.assertEqual(request.confirmation, "DELETE ALL KNOWLEDGE")

    def test_purge_deleted_requires_exact_confirmation(self) -> None:
        with self.assertRaises(ValidationError):
            KnowledgePurgeDeletedRequest(confirmation="purge")

        request = KnowledgePurgeDeletedRequest(
            confirmation="PURGE DELETED REGISTRY"
        )
        self.assertEqual(
            request.confirmation,
            "PURGE DELETED REGISTRY",
        )

    def test_openai_compatible_routes_are_exposed(self) -> None:
        routes = {
            (route.path, method)
            for route in openai_knowledge_router.routes
            for method in route.methods
        }
        self.assertIn(("/v1/models", "GET"), routes)
        self.assertIn(("/v1/chat/completions", "POST"), routes)

    def test_direct_search_and_chat_are_deprecated_compatibility(
        self,
    ) -> None:
        routes = {
            (route.path, method): route
            for route in knowledge_router.routes
            for method in route.methods
        }

        self.assertTrue(routes[("/knowledge/search", "POST")].deprecated)
        self.assertTrue(routes[("/knowledge/chat", "POST")].deprecated)

    def test_legacy_registry_cleanup_routes_are_deprecated(self) -> None:
        routes = {
            (route.path, method): route
            for route in knowledge_router.routes
            for method in route.methods
        }

        for key in (
            ("/knowledge/documents/bulk/purge", "POST"),
            ("/knowledge/documents/purge-deleted", "POST"),
            ("/knowledge/documents/{document_id}/registry", "DELETE"),
        ):
            self.assertTrue(routes[key].deprecated)

    def test_audio_lab_lifecycle_routes_are_deprecated_compatibility(
        self,
    ) -> None:
        routes = {
            (route.path, method): route
            for route in audio_lab_router.routes
            for method in route.methods
        }
        self.assertIn(("/audio-lab/tasks", "GET"), routes)
        compatibility_routes = {
            ("/audio-lab/tasks/{task_id}/index", "POST"),
            ("/audio-lab/tasks/{task_id}/reindex", "POST"),
            ("/audio-lab/tasks/{task_id}/index", "DELETE"),
        }

        for route_key in compatibility_routes:
            self.assertIn(route_key, routes)
            self.assertTrue(routes[route_key].deprecated)


class OpenAIKnowledgeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_models_exposes_single_knowledge_model(self) -> None:
        result = await list_knowledge_models()

        self.assertEqual(
            [model["id"] for model in result["data"]],
            ["homelab-knowledge"],
        )

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
            "answer": "Відповідь із бази [Джерело 1].",
            "sources": [
                {
                    "number": 1,
                    "source_filename": "book.pdf",
                    "score": 0.91,
                },
                {
                    "number": 2,
                    "source_filename": "unused.pdf",
                    "score": 0.88,
                },
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
        self.assertIn("Відповідь із бази", content)
        self.assertIn("[1] book.pdf", content)
        self.assertNotIn("unused.pdf", content)
        chat.assert_awaited_once()
        self.assertEqual(chat.await_args.args[0], "Уточни відповідь")
        self.assertEqual(
            len(chat.await_args.kwargs["conversation_messages"]),
            3,
        )
        self.assertEqual(
            chat.await_args.kwargs["limit"],
            settings.knowledge_chat_limit,
        )


class OpenAIKnowledgeSourceTests(unittest.TestCase):
    sources = [
        {
            "number": 1,
            "source_filename": "first.pdf",
            "score": 0.91,
        },
        {
            "number": 2,
            "source_filename": "second.pdf",
            "score": 0.82,
        },
        {
            "number": 3,
            "source_filename": "third.pdf",
            "score": 0.73,
        },
    ]

    def answer_with_sources(self, answer: str) -> str:
        return _answer_with_sources(
            {
                "answer": answer,
                "sources": self.sources,
            }
        )

    def test_one_valid_citation_shows_only_that_source(self) -> None:
        content = self.answer_with_sources("Answer [Джерело 2].")

        self.assertNotIn("first.pdf", content)
        self.assertIn("[2] second.pdf", content)
        self.assertNotIn("third.pdf", content)

    def test_multiple_valid_citations_show_only_those_sources(self) -> None:
        content = self.answer_with_sources(
            "Answer [Джерело 1] and [Джерело 3]."
        )

        self.assertIn("[1] first.pdf", content)
        self.assertNotIn("second.pdf", content)
        self.assertIn("[3] third.pdf", content)

    def test_no_citations_adds_no_source_footer(self) -> None:
        answer = "Answer without a citation."

        self.assertEqual(self.answer_with_sources(answer), answer)

    def test_invalid_citation_adds_no_source_footer(self) -> None:
        answer = "Answer [Джерело 99]."

        self.assertEqual(self.answer_with_sources(answer), answer)

    def test_mixed_valid_and_invalid_citations_show_only_valid_source(
        self,
    ) -> None:
        content = self.answer_with_sources(
            "Answer [Джерело 2] and [Джерело 99]."
        )

        self.assertNotIn("first.pdf", content)
        self.assertIn("[2] second.pdf", content)
        self.assertNotIn("third.pdf", content)


if __name__ == "__main__":
    unittest.main()
