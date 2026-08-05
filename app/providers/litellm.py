from typing import Any

import httpx

from app.config import settings
from app.providers.http import endpoint_available


def auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}

    if settings.litellm_api_key:
        headers["Authorization"] = (
            f"Bearer {settings.litellm_api_key}"
        )

    return headers


async def available() -> bool:
    return await endpoint_available(
        f"{settings.litellm_url}/v1/models",
        timeout=3.0,
        headers=auth_headers(),
    )


async def list_models() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.litellm_url}/v1/models",
                headers=auth_headers(),
            )

        if response.status_code != 200:
            return []

        payload = response.json()
        models = payload.get("data", [])

        return [
            model
            for model in models
            if isinstance(model, dict)
        ]

    except (httpx.HTTPError, ValueError):
        return []


async def chat_completion(
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=1800.0) as client:
        response = await client.post(
            f"{settings.litellm_url}/v1/chat/completions",
            headers=auth_headers(),
            json=payload,
        )

    response.raise_for_status()
    return response.json()
