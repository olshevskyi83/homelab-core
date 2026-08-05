from typing import Any

from pydantic import BaseModel


class QueueDashboard(BaseModel):
    total: int
    waiting: int
    running: int
    completed: int
    failed: int
    cancelled: int


class MacDashboard(BaseModel):
    online: bool
    hostname: str | None
    cpu_percent: float | None
    memory_percent: float | None


class LLMDashboard(BaseModel):
    litellm: bool
    lm_studio: bool
    worker_ready: bool


class WhisperDashboard(BaseModel):
    mac_agent: bool
    mac_running: bool
    server_running: bool
    active_jobs: int
    idle_seconds: int | None
    shutdown_after_seconds: int


class DashboardResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: int
    schema_version: int

    queue: QueueDashboard
    mac: MacDashboard
    llm: LLMDashboard
    whisper: WhisperDashboard


class SystemResponse(BaseModel):
    dashboard: DashboardResponse
    mac_agent_raw: dict[str, Any] | None
