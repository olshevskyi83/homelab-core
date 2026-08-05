from fastapi import APIRouter

from app.services.resource_manager import can_run_mac_llm
from app.services.resource_manager import can_start_mac_whisper


router = APIRouter(
    prefix="/resources",
    tags=["resources"],
)


@router.get("/mac")
async def mac_resources() -> dict:
    llm = await can_run_mac_llm()
    whisper = await can_start_mac_whisper()

    return {
        "policy": {
            "llm": {
                "allowed": llm.allowed,
                "reason": llm.reason,
            },
            "whisper": {
                "allowed": whisper.allowed,
                "reason": whisper.reason,
            },
        },
        "mac": {
            "online": llm.mac_online or whisper.mac_online,
            "memory_percent": (
                llm.memory_percent
                if llm.memory_percent is not None
                else whisper.memory_percent
            ),
            "lm_studio_running": llm.lm_studio_running,
            "whisper_running": whisper.whisper_running,
        },
    }
