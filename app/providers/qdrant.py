from typing import Any

import httpx

from app.config import settings


async def available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{settings.qdrant_url}/collections"
            )

        return response.status_code == 200

    except httpx.HTTPError:
        return False


async def collection_exists() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.qdrant_url}/collections/"
                f"{settings.qdrant_collection}"
            )

        return response.status_code == 200

    except httpx.HTTPError:
        return False


async def ensure_collection(vector_size: int) -> None:
    if vector_size < 1:
        raise ValueError("Vector size must be positive")

    if await collection_exists():
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            f"{settings.qdrant_url}/collections/"
            f"{settings.qdrant_collection}",
            json={
                "vectors": {
                    "size": vector_size,
                    "distance": "Cosine",
                    "on_disk": True,
                },
                "on_disk_payload": True,
            },
        )

    if response.status_code not in {200, 201}:
        raise RuntimeError(
            f"Could not create Qdrant collection: "
            f"HTTP {response.status_code}: {response.text[:2000]}"
        )


async def upsert_points(
    points: list[dict[str, Any]],
) -> None:
    if not points:
        return

    async with httpx.AsyncClient(timeout=1800.0) as client:
        response = await client.put(
            f"{settings.qdrant_url}/collections/"
            f"{settings.qdrant_collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )

    response.raise_for_status()


async def delete_document(document_id: str) -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/"
            f"{settings.qdrant_collection}/points/delete",
            params={"wait": "true"},
            json={
                "filter": {
                    "must": [
                        {
                            "key": "document_id",
                            "match": {
                                "value": document_id,
                            },
                        }
                    ]
                }
            },
        )

    if response.status_code == 404:
        return

    response.raise_for_status()


async def count_document_points(document_id: str) -> int:
    if not await collection_exists():
        return 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/"
            f"{settings.qdrant_collection}/points/count",
            json={
                "filter": {
                    "must": [
                        {
                            "key": "document_id",
                            "match": {
                                "value": document_id,
                            },
                        }
                    ]
                },
                "exact": True,
            },
        )

    response.raise_for_status()
    payload = response.json()

    return int(
        payload.get("result", {}).get("count", 0)
    )


async def search_points(
    vector: list[float],
    *,
    limit: int = 5,
    score_threshold: float | None = None,
    source_type: str | None = None,
    project: str | None = None,
) -> list[dict[str, Any]]:
    if not await collection_exists():
        return []

    must_filters: list[dict[str, Any]] = []

    if source_type:
        must_filters.append(
            {
                "key": "source_type",
                "match": {
                    "value": source_type,
                },
            }
        )

    if project:
        must_filters.append(
            {
                "key": "project",
                "match": {
                    "value": project,
                },
            }
        )

    body: dict[str, Any] = {
        "query": vector,
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
    }

    if score_threshold is not None:
        body["score_threshold"] = score_threshold

    if must_filters:
        body["filter"] = {
            "must": must_filters,
        }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/"
            f"{settings.qdrant_collection}/points/query",
            json=body,
        )

    response.raise_for_status()
    payload = response.json()

    result = payload.get("result", {})

    if isinstance(result, dict):
        points = result.get("points", [])
    else:
        points = result

    if not isinstance(points, list):
        return []

    return [
        point
        for point in points
        if isinstance(point, dict)
    ]
