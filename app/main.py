import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api import dashboard
from app.api import embeddings
from app.api import health
from app.api import llm
from app.api import models
from app.api import resources
from app.api import tasks
from app.api import whisper
from app.services import task_service
from app.services.llm_worker import llm_worker
from app.services.whisper_service import whisper_service
from app.storage.database import initialize_database
from app.utils.logging import configure_logging


configure_logging()




@asynccontextmanager
async def lifespan(_: FastAPI):
    schema_version = await initialize_database()
    recovered = await task_service.recover_interrupted_tasks()

    logging.getLogger(__name__).info(
        "Database schema version: %s; recovered tasks: %s",
        schema_version,
        recovered,
    )

    whisper_watcher = asyncio.create_task(
        whisper_service.idle_watcher()
    )

    llm_worker_task = asyncio.create_task(
        llm_worker.run()
    )

    try:
        yield
    finally:
        for task in (
            whisper_watcher,
            llm_worker_task,
        ):
            task.cancel()

        for task in (
            whisper_watcher,
            llm_worker_task,
        ):
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Homelab Core",
    version="1.3.0",
    lifespan=lifespan,
)

app.include_router(dashboard.router)
app.include_router(health.router)
app.include_router(whisper.router)
app.include_router(llm.router)
app.include_router(models.router)
app.include_router(resources.router)
app.include_router(embeddings.router)
app.include_router(tasks.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "Homelab Core",
        "version": "1.3.0",
        "status": "running",
    }
