from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.storage.database import connect


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def register_document(
    *,
    document_id: str,
    text_path: str,
    source_type: str,
    project: str,
    source_filename: str,
) -> dict[str, Any]:
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
            VALUES (?, NULL, ?, ?, ?, ?, 'not_indexed', 0, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                source_type = excluded.source_type,
                project = excluded.project,
                source_filename = excluded.source_filename,
                text_path = excluded.text_path,
                index_status = CASE
                    WHEN knowledge_documents.text_path = excluded.text_path
                    THEN knowledge_documents.index_status
                    ELSE 'not_indexed'
                END,
                chunk_count = CASE
                    WHEN knowledge_documents.text_path = excluded.text_path
                    THEN knowledge_documents.chunk_count
                    ELSE 0
                END,
                error = NULL,
                updated_at = excluded.updated_at
            """,
            (
                document_id,
                source_type,
                project,
                source_filename,
                text_path,
                utc_now(),
            ),
        )
        await database.commit()

        cursor = await database.execute(
            "SELECT * FROM knowledge_documents WHERE document_id = ?",
            (document_id,),
        )
        row = await cursor.fetchone()
        return dict(row)
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


async def query_documents(
    *,
    source_type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conditions: list[str] = []
    parameters: list[Any] = []

    if source_type:
        conditions.append("source_type = ?")
        parameters.append(source_type)

    if project:
        conditions.append("project = ?")
        parameters.append(project)

    if status in {None, "active", "all"}:
        conditions.append("index_status != 'deleted'")
    elif status:
        conditions.append("index_status = ?")
        parameters.append(status)

    normalized_query = (query or "").strip().lower()

    if normalized_query:
        conditions.append(
            "LOWER(COALESCE(source_filename, '')) LIKE ?"
        )
        parameters.append(f"%{normalized_query}%")

    where_clause = (
        " WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )
    database = await connect()

    try:
        count_cursor = await database.execute(
            "SELECT COUNT(*) AS total "
            "FROM knowledge_documents"
            f"{where_clause}",
            parameters,
        )
        count_row = await count_cursor.fetchone()
        total = int(count_row["total"]) if count_row else 0

        sql = (
            "SELECT * FROM knowledge_documents"
            f"{where_clause} "
            "ORDER BY updated_at DESC, document_id ASC"
        )
        page_parameters = list(parameters)

        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            page_parameters.extend((limit, offset))

        cursor = await database.execute(sql, page_parameters)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows], total

    finally:
        await database.close()


async def purge_document(document_id: str) -> bool:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            DELETE FROM knowledge_documents
            WHERE document_id = ?
              AND index_status = 'deleted'
            """,
            (document_id,),
        )
        await database.commit()
        return cursor.rowcount == 1

    finally:
        await database.close()


async def delete_document(document_id: str) -> bool:
    """Physically remove a Knowledge registry row after vector deletion."""
    database = await connect()

    try:
        cursor = await database.execute(
            "DELETE FROM knowledge_documents WHERE document_id = ?",
            (document_id,),
        )
        await database.commit()
        return cursor.rowcount == 1

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
