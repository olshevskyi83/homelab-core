import httpx

from app.config import settings
from app.providers.http import endpoint_available


async def available() -> bool:
    return await endpoint_available(
        f"{settings.mac_whisper_url}/v1/models",
        timeout=2.0,
    )


async def transcribe(
    *,
    filename: str,
    content: bytes,
    content_type: str,
    fields: dict[str, str],
) -> httpx.Response:
    files = {
        "file": (
            filename,
            content,
            content_type,
        )
    }

    data = {
        **fields,
        "model": settings.mac_whisper_model,
    }

    async with httpx.AsyncClient(timeout=1800.0) as client:
        return await client.post(
            f"{settings.mac_whisper_url}/v1/audio/transcriptions",
            data=data,
            files=files,
        )
