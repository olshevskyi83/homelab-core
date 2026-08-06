from fastapi import APIRouter, HTTPException

from app.models.knowledge import (
    KnowledgeChatRequest,
    KnowledgeSearchRequest,
)
from app.services import knowledge_service


router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)


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
