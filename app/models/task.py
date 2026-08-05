from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(StrEnum):
    WHISPER = "whisper"
    LLM = "llm"
    EMBEDDING = "embedding"
    OCR = "ocr"
    IMAGE = "image"
    SYSTEM = "system"


class TaskProvider(StrEnum):
    AUTO = "auto"
    MAC = "mac"
    SERVER = "server"
    GPU = "gpu"
    CLOUD = "cloud"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    type: TaskType
    provider: TaskProvider = TaskProvider.AUTO
    priority: TaskPriority = TaskPriority.NORMAL
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)


class TaskResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime

    type: TaskType
    provider: TaskProvider
    status: TaskStatus
    priority: TaskPriority

    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None

    attempts: int
    max_attempts: int


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    limit: int
    offset: int


class TaskStatsResponse(BaseModel):
    total: int
    waiting: int
    running: int
    completed: int
    failed: int
    cancelled: int
