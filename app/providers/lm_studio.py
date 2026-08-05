from typing import Any

import httpx

from app.config import settings
from app.providers.http import endpoint_available


LM_STUDIO_URL = f"http://{settings.mac_host}:1234"


async def available() -> bool:
    return await endpoint_available(
        f"{LM_STUDIO_URL}/v1/models",
        timeout=3.0,
    )


async def list_models() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{LM_STUDIO_URL}/v1/models"
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
