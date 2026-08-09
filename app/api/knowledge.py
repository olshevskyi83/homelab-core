from fastapi import APIRouter, HTTPException

from app.models.knowledge import (
    KnowledgeChatRequest,
    KnowledgeDocumentRegistration,
    KnowledgeSearchRequest,
)
from app.services import knowledge_service


router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)


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


@router.post("/search")
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


@router.post("/chat")
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
