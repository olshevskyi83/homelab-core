import asyncio
import time

from app.config import settings
from app.models.dashboard import DashboardResponse
from app.models.dashboard import LLMDashboard
from app.models.dashboard import MacDashboard
from app.models.dashboard import QueueDashboard
from app.models.dashboard import SystemResponse
from app.models.dashboard import WhisperDashboard
from app.providers import litellm
from app.providers import lm_studio
from app.providers import mac_agent
from app.providers import mac_whisper
from app.providers import server_whisper
from app.services import task_service
from app.services.whisper_service import whisper_service
from app.storage.database import get_schema_version


SERVICE_STARTED_AT = time.monotonic()


async def build_dashboard() -> DashboardResponse:
    (
        queue_stats,
        schema_version,
        mac_data,
        litellm_ok,
        lm_studio_ok,
        mac_whisper_ok,
        server_whisper_ok,
    ) = await asyncio.gather(
        task_service.get_stats(),
        get_schema_version(),
        mac_agent.health(),
        litellm.available(),
        lm_studio.available(),
        mac_whisper.available(),
        server_whisper.available(),
    )

    active_jobs, idle_seconds, active_backend = (
        await whisper_service.runtime_status()
    )

    mac_online = mac_data is not None

    critical_ok = (
        litellm_ok
        and server_whisper_ok
    )

    status = "ok" if critical_ok else "degraded"

    return DashboardResponse(
        status=status,
        service="Homelab Core",
        version="1.3.0",
        uptime_seconds=int(
            time.monotonic() - SERVICE_STARTED_AT
        ),
        schema_version=schema_version,

        queue=QueueDashboard(**queue_stats),

        mac=MacDashboard(
            online=mac_online,
            hostname=(
                str(mac_data.get("hostname"))
                if mac_data and mac_data.get("hostname")
                else None
            ),
            cpu_percent=(
                float(mac_data["cpu_percent"])
                if mac_data
                and mac_data.get("cpu_percent") is not None
                else None
            ),
            memory_percent=(
                float(mac_data["memory_percent"])
                if mac_data
                and mac_data.get("memory_percent") is not None
                else None
            ),
        ),

        llm=LLMDashboard(
            litellm=litellm_ok,
            lm_studio=lm_studio_ok,
            worker_ready=litellm_ok and lm_studio_ok,
        ),

        whisper=WhisperDashboard(
            mac_agent=mac_online,
            mac_available=mac_online,
            mac_running=mac_whisper_ok,
            server_available=server_whisper_ok,
            server_running=server_whisper_ok,
            active_backend=active_backend,
            active_jobs=active_jobs,
            idle_seconds=idle_seconds,
            shutdown_after_seconds=(
                settings.whisper_idle_seconds
            ),
        ),
    )


async def build_system_status() -> SystemResponse:
    dashboard, mac_data = await asyncio.gather(
        build_dashboard(),
        mac_agent.health(),
    )

    return SystemResponse(
        dashboard=dashboard,
        mac_agent_raw=mac_data,
    )
