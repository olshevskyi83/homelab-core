from fastapi import APIRouter

from app.models.health import HealthResponse
from app.services.health_service import get_health


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await get_health()
