from fastapi import APIRouter


router = APIRouter(
    prefix="/v1",
    tags=["embeddings"],
)


@router.get("/embeddings/status")
async def embeddings_status() -> dict[str, str]:
    return {
        "status": "reserved",
        "message": "Embedding routing will be added later",
    }
