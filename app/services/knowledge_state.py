from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.storage.database import connect


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def ensure_document(
    *,
    document_id: str,
    task_id: str,
    source_filename: str | None,
    text_path: str | None,
) -> None:
    database = await connect()

    try:
        await database.execute(
            """
            INSERT INTO knowledge_documents (
                document_id,
                task_id,
                source_type,
                project,
                source_filename,
                text_path,
                index_status,
                chunk_count,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'not_indexed', 0, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                source_filename = excluded.source_filename,
                text_path = excluded.text_path,
                updated_at = excluded.updated_at
            """,
            (
                document_id,
                task_id,
                "transcription",
                "audio-lab",
                source_filename,
                text_path,
                utc_now(),
            ),
        )

        await database.commit()

    finally:
        await database.close()


async def get_document(
    document_id: str,
) -> dict[str, Any] | None:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            SELECT *
            FROM knowledge_documents
            WHERE document_id = ?
            """,
            (document_id,),
        )

        row = await cursor.fetchone()

        return dict(row) if row else None

    finally:
        await database.close()


async def list_documents() -> list[dict[str, Any]]:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            SELECT *
            FROM knowledge_documents
            ORDER BY updated_at DESC
            """
        )

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    finally:
        await database.close()


async def set_status(
    document_id: str,
    status: str,
    *,
    chunk_count: int | None = None,
    error: str | None = None,
    indexed: bool = False,
) -> None:
    database = await connect()

    try:
        await database.execute(
            """
            UPDATE knowledge_documents
            SET
                index_status = ?,
                chunk_count = COALESCE(?, chunk_count),
                embedding_model = ?,
                collection_name = ?,
                indexed_at = CASE
                    WHEN ? THEN ?
                    ELSE indexed_at
                END,
                updated_at = ?,
                error = ?
            WHERE document_id = ?
            """,
            (
                status,
                chunk_count,
                settings.embedding_model,
                settings.qdrant_collection,
                1 if indexed else 0,
                utc_now(),
                utc_now(),
                error[:4000] if error else None,
                document_id,
            ),
        )

        await database.commit()

    finally:
        await database.close()
