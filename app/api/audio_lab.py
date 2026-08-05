from fastapi import APIRouter, HTTPException, Query

from app.services import knowledge_service
from app.services import knowledge_state
from app.services import task_service


router = APIRouter(
    prefix="/audio-lab",
    tags=["audio-lab"],
)


@router.get("/tasks")
async def audio_tasks(
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    await knowledge_service.register_completed_transcriptions()

    documents = {
        item["task_id"]: item
        for item in await knowledge_state.list_documents()
    }

    tasks, total = await task_service.list_tasks(
        task_type="whisper",
        limit=limit,
        offset=0,
    )

    return {
        "tasks": [
            {
                "id": task.id,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "status": task.status.value,
                "priority": task.priority.value,
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
                "source_file": task.payload.get(
                    "original_filename"
                ),
                "file_path": task.payload.get("file_path"),
                "source": task.payload.get("source"),
                "language": task.payload.get("language"),
                "result": task.result,
                "error": task.error,
                "index": documents.get(task.id),
            }
            for task in tasks
        ],
        "total": total,
    }


@router.post("/tasks/{task_id}/index")
async def index_task(task_id: str) -> dict:
    try:
        return await knowledge_service.index_document(task_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@router.post("/tasks/{task_id}/reindex")
async def reindex_task(task_id: str) -> dict:
    try:
        return await knowledge_service.index_document(task_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@router.delete("/tasks/{task_id}/index")
async def delete_task_index(task_id: str) -> dict:
    try:
        return await knowledge_service.delete_document_index(
            task_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
