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


def resolve_document_path(path: str) -> Path:
    documents_root = Path(settings.documents_root).resolve()
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = documents_root / candidate

    resolved = candidate.resolve()

    if resolved == documents_root or documents_root not in resolved.parents:
        raise ValueError("Document path is outside DOCUMENTS_ROOT")

    if not resolved.exists():
        raise FileNotFoundError(f"Document file not found: {resolved}")

    if not resolved.is_file():
        raise ValueError("Document path must point to a file")

    return resolved


async def register_document(
    *,
    path: str,
    document_id: str | None = None,
    source_type: str = "document",
    project: str = "document-lab",
    source_filename: str | None = None,
) -> dict:
    resolved = resolve_document_path(path)
    normalized_id = (document_id or "").strip() or str(
        uuid5(NAMESPACE_URL, str(resolved))
    )
    normalized_source_type = source_type.strip()
    normalized_project = project.strip()

    if not normalized_source_type or not normalized_project:
        raise ValueError("Source type and project must not be blank")

    existing = await knowledge_state.get_document(normalized_id)

    if existing and existing.get("task_id"):
        raise ValueError(
            "Document ID belongs to an Audio Lab transcription"
        )

    return await knowledge_state.register_document(
        document_id=normalized_id,
        text_path=str(resolved),
        source_type=normalized_source_type,
        project=normalized_project,
        source_filename=source_filename or resolved.name,
    )


async def get_document_status(document_id: str) -> dict:
    document = await knowledge_state.get_document(document_id)

    if document is None:
        raise ValueError("Knowledge document not found")

    return document


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

    if document.get("task_id"):
        text_path = Path(str(text_path_raw)).resolve()
        audio_root = Path(settings.audio_root).resolve()

        if text_path == audio_root or audio_root not in text_path.parents:
            raise ValueError("Text file is outside Audio root")
    else:
        text_path = resolve_document_path(str(text_path_raw))

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


async def delete_document(document_id: str) -> dict:
    """Remove a document from Knowledge without touching its source file."""
    document = await knowledge_state.get_document(document_id)

    if document is None:
        raise ValueError("Knowledge document not found")

    # Do not report or record success unless Qdrant deletion succeeded.
    await qdrant.delete_document(document_id)

    await knowledge_state.set_status(
        document_id,
        "deleted",
        chunk_count=0,
        error=None,
    )

    return {
        "document_id": document_id,
        "index_deleted": True,
        "status": "deleted",
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

    points = await qdrant.search_point_groups(
        vectors[0],
        limit=limit,
        group_size=2,
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


async def chat_with_knowledge(
    query: str,
    *,
    model: str = "qwen-general",
    conversation_messages: list[dict] | None = None,
    limit: int = 5,
    source_type: str | None = None,
    project: str | None = None,
    score_threshold: float | None = None,
    temperature: float = 0.2,
) -> dict:
    search = await search_knowledge(
        query,
        limit=limit,
        source_type=source_type,
        project=project,
        score_threshold=score_threshold,
    )

    results = search["results"]

    if not results:
        return {
            "query": search["query"],
            "answer": (
                "У базі знань не знайдено релевантних "
                "джерел для відповіді."
            ),
            "model": model,
            "sources": [],
            "usage": None,
        }

    context_blocks: list[str] = []

    for index, result in enumerate(results, start=1):
        filename = result.get("source_filename") or "Без назви"
        text = str(result.get("text") or "").strip()

        context_blocks.append(
            f"[Джерело {index}]\n"
            f"Файл: {filename}\n"
            f"Текст: {text}"
        )

    context = "\n\n".join(context_blocks)

    system_prompt = (
        "Ти відповідаєш лише на основі переданих джерел із "
        "локальної бази знань. Не вигадуй фактів, яких немає "
        "у контексті. Якщо інформації недостатньо, прямо скажи "
        "про це. Відповідай мовою запиту. Для важливих тверджень "
        "вказуй номер джерела у форматі [Джерело 1]."
    )

    user_prompt = (
        f"Питання:\n{search['query']}\n\n"
        f"Джерела:\n{context}\n\n"
        "Сформуй чітку відповідь."
    )

    messages: list[dict] = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    if conversation_messages:
        messages.extend(conversation_messages[:-1])

    messages.append(
        {
            "role": "user",
            "content": user_prompt,
        }
    )

    completion = await litellm.chat_completion(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
    )

    choices = completion.get("choices") or []

    if not choices:
        raise RuntimeError("LLM response contains no choices")

    message = choices[0].get("message") or {}
    answer = str(message.get("content") or "").strip()

    if not answer:
        raise RuntimeError("LLM returned an empty answer")

    sources = [
        {
            "number": index,
            "source_filename": result.get("source_filename"),
            "score": result.get("score"),
            "document_id": result.get("document_id"),
            "task_id": result.get("task_id"),
            "source_type": result.get("source_type"),
            "project": result.get("project"),
            "chunk_index": result.get("chunk_index"),
            "chunk_count": result.get("chunk_count"),
            "text": result.get("text"),
        }
        for index, result in enumerate(results, start=1)
    ]

    return {
        "query": search["query"],
        "answer": answer,
        "model": completion.get("model") or model,
        "sources": sources,
        "usage": completion.get("usage"),
    }
