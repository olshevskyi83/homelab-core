from fastapi import APIRouter, HTTPException, Query

from app.models.knowledge import (
    KnowledgeBulkRequest,
    KnowledgeChatRequest,
    KnowledgeDeleteAllRequest,
    KnowledgeDocumentRegistration,
    KnowledgePurgeDeletedRequest,
    KnowledgeSearchRequest,
    KnowledgeTranscriptionRegistration,
)
from app.services import knowledge_service


router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)


# Ingestion Boundary
# Labs may register approved local artifacts here. Homelab Core owns every
# Knowledge lifecycle operation after registration.
@router.post("/documents", status_code=201)
async def register_document(
    request: KnowledgeDocumentRegistration,
) -> dict:
    try:
        return await knowledge_service.register_document(
            path=request.path,
            document_id=request.document_id,
            source_type=request.source_type,
            project=request.project,
            source_filename=request.source_filename,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transcriptions", status_code=201)
async def register_transcription(
    request: KnowledgeTranscriptionRegistration,
) -> dict:
    """Register an Audio Lab session transcript from the fixed AUDIO_ROOT."""
    try:
        return await knowledge_service.register_transcription(
            document_id=request.document_id,
            text_path=request.text_path,
            source_filename=request.source_filename,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Knowledge Management
# This router is the sole lifecycle API for the future Knowledge Manager UI.
@router.get("/documents")
async def list_documents(
    source_type: str | None = None,
    project: str | None = None,
    status: str | None = "active",
    source_available: bool | None = None,
    query: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await knowledge_service.list_knowledge_documents(
        source_type=source_type,
        project=project,
        status=status,
        source_available=source_available,
        query=query,
        limit=limit,
        offset=offset,
    )


async def _bulk_documents(
    request: KnowledgeBulkRequest,
    operation: str,
) -> dict:
    return await knowledge_service.bulk_document_operation(
        request.document_ids,
        operation,
    )


@router.post("/documents/bulk/index")
async def bulk_index(request: KnowledgeBulkRequest) -> dict:
    return await _bulk_documents(request, "index")


@router.post("/documents/bulk/reindex")
async def bulk_reindex(request: KnowledgeBulkRequest) -> dict:
    return await _bulk_documents(request, "reindex")


@router.post("/documents/bulk/retry")
async def bulk_retry(request: KnowledgeBulkRequest) -> dict:
    return await _bulk_documents(request, "retry")


@router.post("/documents/bulk/delete-index")
async def bulk_delete_index(request: KnowledgeBulkRequest) -> dict:
    return await _bulk_documents(request, "delete-index")


@router.post("/documents/bulk/delete")
async def bulk_delete(request: KnowledgeBulkRequest) -> dict:
    return await _bulk_documents(request, "delete")


@router.post("/documents/bulk/purge", deprecated=True)
async def bulk_purge(request: KnowledgeBulkRequest) -> dict:
    """Compatibility cleanup for legacy deleted registry rows."""
    return await _bulk_documents(request, "purge")


@router.post("/documents/delete-all")
async def delete_all(request: KnowledgeDeleteAllRequest) -> dict:
    return await knowledge_service.delete_all_documents()


@router.post("/documents/purge-deleted", deprecated=True)
async def purge_deleted(request: KnowledgePurgeDeletedRequest) -> dict:
    """Compatibility cleanup for legacy deleted registry rows."""
    return await knowledge_service.purge_deleted_registry()


@router.get("/documents/{document_id}")
async def document_status(document_id: str) -> dict:
    try:
        return await knowledge_service.get_document_status(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/{document_id}/status")
async def explicit_document_status(document_id: str) -> dict:
    return await document_status(document_id)


async def _index_document(document_id: str) -> dict:
    try:
        return await knowledge_service.index_document(document_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/documents/{document_id}/index")
async def index_document(document_id: str) -> dict:
    return await _index_document(document_id)


@router.post("/documents/{document_id}/reindex")
async def reindex_document(document_id: str) -> dict:
    return await _index_document(document_id)


@router.delete("/documents/{document_id}/index")
async def delete_document_index(document_id: str) -> dict:
    try:
        return await knowledge_service.delete_document_index(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str) -> dict:
    try:
        return await knowledge_service.delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/documents/{document_id}/registry", deprecated=True)
async def purge_document_registry(document_id: str) -> dict:
    """Compatibility cleanup for a legacy deleted registry row."""
    try:
        return await knowledge_service.purge_document_registry(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# Compatibility Layer
# Retained for direct API clients. Labs must not add search/chat UI; Open WebUI
# is the supported chat client through /v1/chat/completions.
@router.post("/search", deprecated=True)
async def search(
    request: KnowledgeSearchRequest,
) -> dict:
    try:
        return await knowledge_service.search_knowledge(
            request.query,
            limit=request.limit,
            source_type=request.source_type,
            project=request.project,
            score_threshold=request.score_threshold,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@router.post("/chat", deprecated=True)
async def chat(
    request: KnowledgeChatRequest,
) -> dict:
    try:
        return await knowledge_service.chat_with_knowledge(
            request.query,
            model=request.model,
            limit=request.limit,
            source_type=request.source_type,
            project=request.project,
            score_threshold=request.score_threshold,
            temperature=request.temperature,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
