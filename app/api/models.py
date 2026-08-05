from fastapi import APIRouter

from app.models.model_info import ModelManagerResponse
from app.services.model_manager import get_models


router = APIRouter(tags=["models"])


@router.get(
    "/models",
    response_model=ModelManagerResponse,
)
async def models() -> ModelManagerResponse:
    return await get_models()
