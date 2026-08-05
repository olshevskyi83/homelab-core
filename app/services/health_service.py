import asyncio

from app.config import settings
from app.models.health import HealthResponse
from app.providers import litellm
from app.providers import mac_agent
from app.providers import mac_whisper
from app.providers import server_whisper
from app.services.whisper_service import whisper_service
from app.storage.database import get_schema_version


async def get_health() -> HealthResponse:
    (
        mac_agent_ok,
        mac_whisper_ok,
        server_whisper_ok,
        litellm_ok,
        schema_version,
    ) = await asyncio.gather(
        mac_agent.available(),
        mac_whisper.available(),
        server_whisper.available(),
        litellm.available(),
        get_schema_version(),
    )

    active_jobs, idle_seconds = (
        await whisper_service.runtime_status()
    )

    status = (
        "ok"
        if server_whisper_ok and litellm_ok
        else "degraded"
    )

    return HealthResponse(
        status=status,
        schema_version=schema_version,
        mac_agent=mac_agent_ok,
        mac_whisper=mac_whisper_ok,
        server_whisper=server_whisper_ok,
        litellm=litellm_ok,
        active_mac_transcriptions=active_jobs,
        mac_whisper_idle_seconds=idle_seconds,
        whisper_shutdown_after_seconds=(
            settings.whisper_idle_seconds
        ),
    )
