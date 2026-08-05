from typing import Any

import httpx

from app.config import settings
from app.providers.http import endpoint_available


def auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.mac_agent_token}"
    }


async def available() -> bool:
    return await endpoint_available(
        f"{settings.mac_agent_url}/health",
        timeout=2.0,
    )


async def health() -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{settings.mac_agent_url}/health",
            )

        if response.status_code != 200:
            return None

        return response.json()

    except (httpx.HTTPError, ValueError):
        return None


async def start_whisper() -> bool:
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{settings.mac_agent_url}/whisper/start",
                headers=auth_headers(),
            )

        return response.status_code == 200

    except httpx.HTTPError:
        return False


async def stop_whisper() -> bool:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{settings.mac_agent_url}/whisper/stop",
                headers=auth_headers(),
            )

        return response.status_code == 200

    except httpx.HTTPError:
        return False
