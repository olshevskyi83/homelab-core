import httpx
from fastapi import APIRouter
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import Response

from app.services.whisper_service import whisper_service
from app.utils.responses import proxy_response


router = APIRouter(
    prefix="/v1/audio",
    tags=["whisper"],
)


@router.post("/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    response_format: str | None = Form(default=None),
    temperature: float | None = Form(default=None),
) -> Response:
    audio = await file.read()

    if not audio:
        raise HTTPException(
            status_code=400,
            detail="Uploaded audio file is empty",
        )

    fields: dict[str, str] = {}

    if language:
        fields["language"] = language

    if prompt:
        fields["prompt"] = prompt

    if response_format:
        fields["response_format"] = response_format

    if temperature is not None:
        fields["temperature"] = str(temperature)

    try:
        response = await whisper_service.transcribe(
            filename=file.filename or "audio",
            content=audio,
            content_type=(
                file.content_type
                or "application/octet-stream"
            ),
            fields=fields,
        )

        return proxy_response(response)

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Both Whisper backends are unavailable: "
                f"{exc}"
            ),
        ) from exc
