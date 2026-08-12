from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(tags=["knowledge-manager-ui"])

FRONTEND_ROOT = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "knowledge_manager"
)


@router.get("/knowledge-manager", include_in_schema=False)
async def knowledge_manager() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "index.html")
