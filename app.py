import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response


# ============================================================
# Configuration
# ============================================================

MAC_HOST = os.environ.get("MAC_HOST", "192.168.178.58")
MAC_AGENT_PORT = int(os.environ.get("MAC_AGENT_PORT", "8010"))
MAC_WHISPER_PORT = int(os.environ.get("MAC_WHISPER_PORT", "8001"))
MAC_AGENT_TOKEN = os.environ["MAC_AGENT_TOKEN"]

MAC_AGENT_URL = f"http://{MAC_HOST}:{MAC_AGENT_PORT}"
MAC_WHISPER_URL = f"http://{MAC_HOST}:{MAC_WHISPER_PORT}"

SERVER_WHISPER_URL = os.environ.get(
    "SERVER_WHISPER_URL",
    "http://whisper:8000",
).rstrip("/")

MAC_WHISPER_MODEL = os.environ.get(
    "MAC_WHISPER_MODEL",
    "whisper-large-v3-turbo",
)

SERVER_WHISPER_MODEL = os.environ.get(
    "SERVER_WHISPER_MODEL",
    "Systran/faster-whisper-medium",
)

WHISPER_IDLE_SECONDS = int(
    os.environ.get("WHISPER_IDLE_SECONDS", "600")
)

LITELLM_URL = os.environ.get(
    "LITELLM_URL",
    "http://litellm:4000",
).rstrip("/")

LITELLM_API_KEY = os.environ.get(
    "LITELLM_API_KEY",
    "",
)


# ============================================================
# Runtime state
# ============================================================

last_mac_whisper_use = 0.0
active_mac_transcriptions = 0

state_lock = asyncio.Lock()
start_lock = asyncio.Lock()


# ============================================================
# Helpers
# ============================================================

async def endpoint_available(
    url: str,
    timeout: float = 2.0,
    headers: dict[str, str] | None = None,
) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def mac_agent_available() -> bool:
    return await endpoint_available(
        f"{MAC_AGENT_URL}/health",
        timeout=2.0,
    )


async def mac_whisper_available() -> bool:
    return await endpoint_available(
        f"{MAC_WHISPER_URL}/v1/models",
        timeout=2.0,
    )


async def server_whisper_available() -> bool:
    return await endpoint_available(
        f"{SERVER_WHISPER_URL}/v1/models",
        timeout=3.0,
    )


async def litellm_available() -> bool:
    headers: dict[str, str] = {}

    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    return await endpoint_available(
        f"{LITELLM_URL}/v1/models",
        timeout=3.0,
        headers=headers,
    )


async def start_mac_whisper() -> bool:
    """
    Start Whisper through the Mac Agent if it is not already running.
    Only one concurrent start attempt is allowed.
    """
    async with start_lock:
        if await mac_whisper_available():
            return True

        if not await mac_agent_available():
            return False

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{MAC_AGENT_URL}/whisper/start",
                    headers={
                        "Authorization": f"Bearer {MAC_AGENT_TOKEN}"
                    },
                )

            if response.status_code != 200:
                return False

        except httpx.HTTPError:
            return False

        # Wait until the Whisper API becomes available.
        for _ in range(90):
            if await mac_whisper_available():
                return True

            await asyncio.sleep(1)

        return False


async def stop_mac_whisper() -> bool:
    """
    Stop Whisper through the Mac Agent.
    """
    if not await mac_agent_available():
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{MAC_AGENT_URL}/whisper/stop",
                headers={
                    "Authorization": f"Bearer {MAC_AGENT_TOKEN}"
                },
            )

        return response.status_code == 200

    except httpx.HTTPError:
        return False


def proxy_response(response: httpx.Response) -> Response:
    """
    Return the upstream response without changing its body format.
    This preserves JSON, text, SRT, VTT and other supported formats.
    """
    content_type = response.headers.get(
        "content-type",
        "application/json",
    )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type.split(";")[0],
    )


async def idle_watcher() -> None:
    """
    Stop Mac Whisper after the configured idle period,
    but never while a transcription is active.
    """
    global last_mac_whisper_use

    while True:
        await asyncio.sleep(30)

        async with state_lock:
            last_use = last_mac_whisper_use
            active_jobs = active_mac_transcriptions

        if last_use <= 0:
            continue

        idle_for = time.time() - last_use

        if (
            active_jobs == 0
            and idle_for >= WHISPER_IDLE_SECONDS
            and await mac_whisper_available()
        ):
            stopped = await stop_mac_whisper()

            if stopped:
                async with state_lock:
                    last_mac_whisper_use = 0.0


# ============================================================
# Application lifecycle
# ============================================================

@asynccontextmanager
async def lifespan(_: FastAPI):
    watcher_task = asyncio.create_task(idle_watcher())

    try:
        yield
    finally:
        watcher_task.cancel()

        with suppress(asyncio.CancelledError):
            await watcher_task


app = FastAPI(
    title="Homelab AI Gateway",
    version="0.2.0",
    lifespan=lifespan,
)


# ============================================================
# Health endpoints
# ============================================================

@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Homelab AI Gateway",
        "version": "0.2.0",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    (
        mac_agent,
        mac_whisper,
        server_whisper,
        litellm,
    ) = await asyncio.gather(
        mac_agent_available(),
        mac_whisper_available(),
        server_whisper_available(),
        litellm_available(),
    )

    async with state_lock:
        last_use = last_mac_whisper_use
        active_jobs = active_mac_transcriptions

    if last_use > 0:
        idle_seconds = max(0, int(time.time() - last_use))
    else:
        idle_seconds = None

    overall_status = (
        "ok"
        if server_whisper and litellm
        else "degraded"
    )

    return {
        "status": overall_status,
        "mac_agent": mac_agent,
        "mac_whisper": mac_whisper,
        "server_whisper": server_whisper,
        "litellm": litellm,
        "active_mac_transcriptions": active_jobs,
        "mac_whisper_idle_seconds": idle_seconds,
        "whisper_shutdown_after_seconds": WHISPER_IDLE_SECONDS,
    }


# ============================================================
# Whisper transcription gateway
# ============================================================

@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    response_format: str | None = Form(default=None),
    temperature: float | None = Form(default=None),
) -> Response:
    global last_mac_whisper_use
    global active_mac_transcriptions

    audio_bytes = await file.read()

    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded audio file is empty",
        )

    common_fields: dict[str, str] = {}

    if language:
        common_fields["language"] = language

    if prompt:
        common_fields["prompt"] = prompt

    if response_format:
        common_fields["response_format"] = response_format

    if temperature is not None:
        common_fields["temperature"] = str(temperature)

    filename = file.filename or "audio"
    content_type = file.content_type or "application/octet-stream"

    # --------------------------------------------------------
    # Primary backend: Mac Whisper
    # --------------------------------------------------------

    mac_started = await start_mac_whisper()

    if mac_started:
        async with state_lock:
            active_mac_transcriptions += 1
            last_mac_whisper_use = time.time()

        try:
            mac_fields = {
                **common_fields,
                "model": MAC_WHISPER_MODEL,
            }

            files = {
                "file": (
                    filename,
                    audio_bytes,
                    content_type,
                )
            }

            async with httpx.AsyncClient(timeout=1800.0) as client:
                response = await client.post(
                    f"{MAC_WHISPER_URL}/v1/audio/transcriptions",
                    data=mac_fields,
                    files=files,
                )

            # Successful requests and normal client errors are
            # returned directly. Server errors trigger fallback.
            if response.status_code < 500:
                return proxy_response(response)

        except httpx.HTTPError:
            pass

        finally:
            async with state_lock:
                active_mac_transcriptions = max(
                    0,
                    active_mac_transcriptions - 1,
                )
                last_mac_whisper_use = time.time()

    # --------------------------------------------------------
    # Fallback backend: Fujitsu CPU Whisper
    # --------------------------------------------------------

    server_fields = {
        **common_fields,
        "model": SERVER_WHISPER_MODEL,
    }

    server_files = {
        "file": (
            filename,
            audio_bytes,
            content_type,
        )
    }

    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            response = await client.post(
                f"{SERVER_WHISPER_URL}/v1/audio/transcriptions",
                data=server_fields,
                files=server_files,
            )

        return proxy_response(response)

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Both Whisper backends are unavailable. "
                f"Server fallback error: {exc}"
            ),
        ) from exc
