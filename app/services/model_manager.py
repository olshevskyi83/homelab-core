import asyncio

from app.config import settings
from app.models.model_info import ModelInfo
from app.models.model_info import ModelManagerResponse
from app.providers import litellm
from app.providers import lm_studio
from app.providers import mac_whisper
from app.providers import server_whisper


def detect_kind(model_id: str) -> str:
    normalized = model_id.lower()

    if "whisper" in normalized:
        return "whisper"

    if "embed" in normalized:
        return "embedding"

    if "coder" in normalized:
        return "llm-coder"

    return "llm"


async def get_models() -> ModelManagerResponse:
    (
        lm_studio_online,
        litellm_online,
        mac_whisper_online,
        server_whisper_online,
        lm_studio_models,
        litellm_models,
    ) = await asyncio.gather(
        lm_studio.available(),
        litellm.available(),
        mac_whisper.available(),
        server_whisper.available(),
        lm_studio.list_models(),
        litellm.list_models(),
    )

    models: list[ModelInfo] = []
    seen: set[tuple[str, str]] = set()

    for raw_model in lm_studio_models:
        model_id = str(raw_model.get("id", "")).strip()

        if not model_id:
            continue

        key = ("lm-studio", model_id)

        if key in seen:
            continue

        seen.add(key)

        models.append(
            ModelInfo(
                id=model_id,
                kind=detect_kind(model_id),
                provider="lm-studio",
                endpoint=f"http://{settings.mac_host}:1234",
                available=True,
                backend_online=lm_studio_online,
            )
        )

    for raw_model in litellm_models:
        model_id = str(raw_model.get("id", "")).strip()

        if not model_id:
            continue

        key = ("litellm", model_id)

        if key in seen:
            continue

        seen.add(key)

        models.append(
            ModelInfo(
                id=model_id,
                kind=detect_kind(model_id),
                provider="litellm",
                endpoint=settings.litellm_url,
                available=True,
                backend_online=litellm_online,
            )
        )

    models.append(
        ModelInfo(
            id=settings.mac_whisper_model,
            kind="whisper",
            provider="mac-whisper",
            endpoint=settings.mac_whisper_url,
            available=mac_whisper_online,
            backend_online=mac_whisper_online,
        )
    )

    models.append(
        ModelInfo(
            id=settings.server_whisper_model,
            kind="whisper",
            provider="server-whisper",
            endpoint=settings.server_whisper_url,
            available=server_whisper_online,
            backend_online=server_whisper_online,
        )
    )

    totals: dict[str, int] = {}

    for model in models:
        totals[model.kind] = totals.get(model.kind, 0) + 1

    critical_backends_ok = (
        litellm_online
        and server_whisper_online
    )

    return ModelManagerResponse(
        status="ok" if critical_backends_ok else "degraded",
        backends={
            "lm_studio": lm_studio_online,
            "litellm": litellm_online,
            "mac_whisper": mac_whisper_online,
            "server_whisper": server_whisper_online,
        },
        models=models,
        totals=totals,
    )
