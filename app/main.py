import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api import audio_lab
from app.api import dashboard
from app.api import embeddings
from app.api import health
from app.api import llm
from app.api import knowledge
from app.api import models
from app.api import resources
from app.api import tasks
from app.api import whisper
from app.services import task_service
from app.services.folder_watcher import folder_watcher
from app.services.llm_worker import llm_worker
from app.services.whisper_service import whisper_service
from app.services.whisper_worker import whisper_worker
from app.storage.database import initialize_database
from app.utils.logging import configure_logging


configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    schema_version = await initialize_database()
    recovered = await task_service.recover_interrupted_tasks()

    logging.getLogger(__name__).info(
        "Homelab Core initialized",
        extra={
            "event": "core_initialized",
            "schema_version": schema_version,
            "recovered_tasks": recovered,
        },
    )

    background_tasks = [
        asyncio.create_task(
            whisper_service.idle_watcher()
        ),
        asyncio.create_task(
            llm_worker.run()
        ),
        asyncio.create_task(
            whisper_worker.run()
        ),
        asyncio.create_task(
            folder_watcher.run()
        ),
    ]

    try:
        yield

    finally:
        for background_task in background_tasks:
            background_task.cancel()

        for background_task in background_tasks:
            with suppress(asyncio.CancelledError):
                await background_task


app = FastAPI(
    title="Homelab Core",
    version="1.5.0",
    lifespan=lifespan,
)

app.include_router(audio_lab.router)
app.include_router(dashboard.router)
app.include_router(health.router)
app.include_router(whisper.router)
app.include_router(llm.router)
app.include_router(knowledge.router)
app.include_router(models.router)
app.include_router(resources.router)
app.include_router(embeddings.router)
app.include_router(tasks.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Homelab Core",
        "version": "1.5.0",
        "status": "running",
    }
