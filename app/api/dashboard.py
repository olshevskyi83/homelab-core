from fastapi import APIRouter

from app.models.dashboard import DashboardResponse
from app.models.dashboard import SystemResponse
from app.services.dashboard_service import build_dashboard
from app.services.dashboard_service import build_system_status


router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
)
async def dashboard() -> DashboardResponse:
    return await build_dashboard()


@router.get(
    "/system",
    response_model=SystemResponse,
)
async def system_status() -> SystemResponse:
    return await build_system_status()
