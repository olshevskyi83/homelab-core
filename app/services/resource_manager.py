from dataclasses import dataclass

from app.config import settings
from app.providers import mac_agent


@dataclass(slots=True)
class ResourceDecision:
    allowed: bool
    reason: str
    mac_online: bool
    memory_percent: float | None
    lm_studio_running: bool
    whisper_running: bool


async def get_mac_state() -> dict | None:
    return await mac_agent.health()


async def can_start_mac_whisper() -> ResourceDecision:
    state = await get_mac_state()

    if state is None:
        return ResourceDecision(
            allowed=False,
            reason="Mac Agent is offline",
            mac_online=False,
            memory_percent=None,
            lm_studio_running=False,
            whisper_running=False,
        )

    memory_percent = _float_or_none(
        state.get("memory_percent")
    )
    lm_studio_running = bool(
        state.get("lm_studio_running", False)
    )
    whisper_running = bool(
        state.get("whisper_running", False)
    )

    if whisper_running:
        return ResourceDecision(
            allowed=True,
            reason="Mac Whisper is already running",
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=lm_studio_running,
            whisper_running=True,
        )

    if (
        memory_percent is not None
        and memory_percent >= settings.mac_memory_limit_percent
    ):
        return ResourceDecision(
            allowed=False,
            reason=(
                f"Mac memory usage is {memory_percent:.1f}% "
                f"(limit {settings.mac_memory_limit_percent:.1f}%)"
            ),
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=lm_studio_running,
            whisper_running=False,
        )

    if (
        lm_studio_running
        and not settings.allow_simultaneous_mac_ai
    ):
        return ResourceDecision(
            allowed=False,
            reason=(
                "LM Studio is active and simultaneous heavy "
                "Mac AI workloads are disabled"
            ),
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=True,
            whisper_running=False,
        )

    return ResourceDecision(
        allowed=True,
        reason="Mac has enough resources for Whisper",
        mac_online=True,
        memory_percent=memory_percent,
        lm_studio_running=lm_studio_running,
        whisper_running=False,
    )


async def can_run_mac_llm() -> ResourceDecision:
    state = await get_mac_state()

    if state is None:
        return ResourceDecision(
            allowed=False,
            reason="Mac Agent is offline",
            mac_online=False,
            memory_percent=None,
            lm_studio_running=False,
            whisper_running=False,
        )

    memory_percent = _float_or_none(
        state.get("memory_percent")
    )
    lm_studio_running = bool(
        state.get("lm_studio_running", False)
    )
    whisper_running = bool(
        state.get("whisper_running", False)
    )

    if not lm_studio_running:
        return ResourceDecision(
            allowed=False,
            reason="LM Studio API is offline",
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=False,
            whisper_running=whisper_running,
        )

    if (
        memory_percent is not None
        and memory_percent >= settings.mac_memory_limit_percent
    ):
        return ResourceDecision(
            allowed=False,
            reason=(
                f"Mac memory usage is {memory_percent:.1f}% "
                f"(limit {settings.mac_memory_limit_percent:.1f}%)"
            ),
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=True,
            whisper_running=whisper_running,
        )

    if (
        whisper_running
        and not settings.allow_simultaneous_mac_ai
    ):
        return ResourceDecision(
            allowed=False,
            reason=(
                "Mac Whisper is active and simultaneous heavy "
                "Mac AI workloads are disabled"
            ),
            mac_online=True,
            memory_percent=memory_percent,
            lm_studio_running=True,
            whisper_running=True,
        )

    return ResourceDecision(
        allowed=True,
        reason="Mac has enough resources for LLM",
        mac_online=True,
        memory_percent=memory_percent,
        lm_studio_running=True,
        whisper_running=whisper_running,
    )


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
