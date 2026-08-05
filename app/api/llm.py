from fastapi import APIRouter


router = APIRouter(
    prefix="/v1",
    tags=["llm"],
)


@router.get("/llm/status")
async def llm_status() -> dict[str, str]:
    return {
        "status": "reserved",
        "message": "LLM queue will be added in the next stage",
    }
