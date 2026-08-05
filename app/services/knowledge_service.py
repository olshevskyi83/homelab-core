from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.config import settings
from app.providers import litellm
from app.providers import qdrant
from app.services import knowledge_state
from app.services import task_service


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def split_text(text: str) -> list[str]:
    normalized = " ".join(text.split()).strip()

    if not normalized:
        return []

    chunk_size = settings.knowledge_chunk_size
    overlap = settings.knowledge_chunk_overlap

    if overlap >= chunk_size:
        raise ValueError(
            "KNOWLEDGE_CHUNK_OVERLAP must be smaller "
            "than KNOWLEDGE_CHUNK_SIZE"
        )

    chunks: list[str] = []
    start = 0

    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))

        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)

            if boundary > start + chunk_size // 2:
                end = boundary

        chunk = normalized[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(normalized):
            break

        start = max(end - overlap, start + 1)

    return chunks


async def register_completed_transcriptions() -> int:
    tasks, _ = await task_service.list_tasks(
        status=None,
        task_type="whisper",
        limit=200,
        offset=0,
    )

    registered = 0

    for task in tasks:
        if task.status.value != "completed" or not task.result:
            continue

        output_files = task.result.get("output_files") or []

        text_path = next(
            (
                str(path)
                for path in output_files
                if str(path).lower().endswith(".txt")
            ),
            None,
        )

        await knowledge_state.ensure_document(
            document_id=task.id,
            task_id=task.id,
            source_filename=(
                task.payload.get("original_filename")
                or Path(
                    str(task.payload.get("file_path", ""))
                ).name
                or None
            ),
            text_path=text_path,
        )

        registered += 1

    return registered


async def index_document(document_id: str) -> dict:
    await register_completed_transcriptions()

    document = await knowledge_state.get_document(document_id)

    if document is None:
        raise ValueError("Knowledge document not found")

    text_path_raw = document.get("text_path")

    if not text_path_raw:
        raise ValueError("Transcription text path is missing")

    text_path = Path(str(text_path_raw)).resolve()
    audio_root = Path(settings.audio_root).resolve()

    if audio_root not in text_path.parents:
        raise ValueError("Text file is outside Audio root")

    if not text_path.exists():
        raise FileNotFoundError(
            f"Transcription file not found: {text_path}"
        )

    text = text_path.read_text(
        encoding="utf-8",
        errors="replace",
    ).strip()

    chunks = split_text(text)

    if not chunks:
        raise ValueError("Transcription contains no indexable text")

    await knowledge_state.set_status(
        document_id,
        "indexing",
        error=None,
    )

    try:
        vectors = await litellm.embeddings(
            chunks,
            settings.embedding_model,
        )

        if len(vectors) != len(chunks):
            raise RuntimeError(
                "Embedding count does not match chunk count"
            )

        await qdrant.ensure_collection(len(vectors[0]))

        # Reindexing is replacement, never duplication.
        await qdrant.delete_document(document_id)

        points = []

        for index, (chunk, vector) in enumerate(
            zip(chunks, vectors, strict=True)
        ):
            point_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{document_id}:{index}",
                )
            )

            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "document_id": document_id,
                        "task_id": document.get("task_id"),
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "source_type": document.get("source_type"),
                        "project": document.get("project"),
                        "source_filename": document.get(
                            "source_filename"
                        ),
                        "text": chunk,
                        "embedding_model": settings.embedding_model,
                        "created_at": utc_now(),
                    },
                }
            )

        await qdrant.upsert_points(points)

        await knowledge_state.set_status(
            document_id,
            "indexed",
            chunk_count=len(points),
            error=None,
            indexed=True,
        )

        return {
            "document_id": document_id,
            "status": "indexed",
            "chunk_count": len(points),
            "collection": settings.qdrant_collection,
            "embedding_model": settings.embedding_model,
        }

    except Exception as exc:
        await knowledge_state.set_status(
            document_id,
            "failed",
            error=str(exc),
        )
        raise


async def delete_document_index(document_id: str) -> dict:
    await register_completed_transcriptions()

    document = await knowledge_state.get_document(document_id)

    if document is None:
        raise ValueError("Knowledge document not found")

    await qdrant.delete_document(document_id)

    await knowledge_state.set_status(
        document_id,
        "not_indexed",
        chunk_count=0,
        error=None,
    )

    return {
        "document_id": document_id,
        "status": "not_indexed",
        "chunk_count": 0,
    }


async def search_knowledge(
    query: str,
    *,
    limit: int = 5,
    source_type: str | None = None,
    project: str | None = None,
    score_threshold: float | None = None,
) -> dict:
    normalized_query = " ".join(query.split()).strip()

    if not normalized_query:
        raise ValueError("Search query is empty")

    vectors = await litellm.embeddings(
        [normalized_query],
        settings.embedding_model,
    )

    if not vectors:
        raise RuntimeError("Could not create query embedding")

    points = await qdrant.search_points(
        vectors[0],
        limit=limit,
        score_threshold=score_threshold,
        source_type=source_type,
        project=project,
    )

    results = []

    for point in points:
        payload = point.get("payload") or {}

        results.append(
            {
                "point_id": point.get("id"),
                "score": point.get("score"),
                "document_id": payload.get("document_id"),
                "task_id": payload.get("task_id"),
                "source_filename": payload.get(
                    "source_filename"
                ),
                "source_type": payload.get("source_type"),
                "project": payload.get("project"),
                "chunk_index": payload.get("chunk_index"),
                "chunk_count": payload.get("chunk_count"),
                "text": payload.get("text"),
            }
        )

    return {
        "query": normalized_query,
        "count": len(results),
        "results": results,
    }
