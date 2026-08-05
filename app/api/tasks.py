from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi import status as http_status

from app.models.task import TaskCreate
from app.models.task import TaskListResponse
from app.models.task import TaskResponse
from app.models.task import TaskStatsResponse
from app.models.task import TaskStatus
from app.services import task_service


router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
)


@router.post(
    "",
    response_model=TaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_task(task: TaskCreate) -> TaskResponse:
    return await task_service.create_task(task)


@router.get("/stats", response_model=TaskStatsResponse)
async def task_stats() -> TaskStatsResponse:
    stats = await task_service.get_stats()
    return TaskStatsResponse(**stats)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: TaskStatus | None = None,
    task_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskListResponse:
    tasks, total = await task_service.list_tasks(
        status=status,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )

    return TaskListResponse(
        tasks=tasks,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    task = await task_service.get_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return task


@router.post(
    "/{task_id}/cancel",
    response_model=TaskResponse,
)
async def cancel_task(task_id: str) -> TaskResponse:
    task = await task_service.cancel_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Task does not exist or can no longer be cancelled"
            ),
        )

    return task


@router.post(
    "/{task_id}/retry",
    response_model=TaskResponse,
)
async def retry_task(task_id: str) -> TaskResponse:
    task = await task_service.retry_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Task cannot be retried or has reached "
                "the maximum attempt count"
            ),
        )

    return task
