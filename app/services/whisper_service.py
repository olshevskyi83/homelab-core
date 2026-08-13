import asyncio
import time

import httpx

from app.config import settings
from app.providers import mac_agent
from app.providers import mac_whisper
from app.providers import server_whisper
from app.services.resource_manager import can_start_mac_whisper


class WhisperService:
    def __init__(self) -> None:
        self.last_mac_use = 0.0
        self.active_mac_jobs = 0
        self.active_backend: str | None = None

        self.state_lock = asyncio.Lock()
        self.start_lock = asyncio.Lock()

    async def ensure_mac_whisper(self) -> bool:
        async with self.start_lock:
            if await mac_whisper.available():
                return True

            decision = await can_start_mac_whisper()

            if not decision.allowed:
                return False

            if not await mac_agent.available():
                return False

            if not await mac_agent.start_whisper():
                return False

            for _ in range(90):
                if await mac_whisper.available():
                    return True

                await asyncio.sleep(1)

            return False

    async def stop_mac_whisper(self) -> bool:
        return await mac_agent.stop_whisper()

    async def transcribe(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        fields: dict[str, str],
        track_active_backend: bool = False,
    ) -> httpx.Response:
        # The queue worker processes one Whisper task at a time. Direct
        # OpenAI-compatible requests intentionally do not alter task runtime.
        mac_started = await self.ensure_mac_whisper()

        if mac_started:
            async with self.state_lock:
                self.active_mac_jobs += 1
                self.last_mac_use = time.time()
                if track_active_backend:
                    self.active_backend = "mac"

            try:
                response = await mac_whisper.transcribe(
                    filename=filename,
                    content=content,
                    content_type=content_type,
                    fields=fields,
                )

                if response.status_code < 500:
                    return response

            except httpx.HTTPError:
                pass

            finally:
                async with self.state_lock:
                    self.active_mac_jobs = max(
                        0,
                        self.active_mac_jobs - 1,
                    )
                    self.last_mac_use = time.time()
                    if track_active_backend:
                        self.active_backend = None

        if track_active_backend:
            async with self.state_lock:
                self.active_backend = "server"

        try:
            return await server_whisper.transcribe(
                filename=filename,
                content=content,
                content_type=content_type,
                fields=fields,
            )
        finally:
            if track_active_backend:
                async with self.state_lock:
                    self.active_backend = None

    async def idle_watcher(self) -> None:
        while True:
            await asyncio.sleep(30)

            async with self.state_lock:
                last_use = self.last_mac_use
                active_jobs = self.active_mac_jobs

            if last_use <= 0:
                continue

            idle_for = time.time() - last_use

            if (
                active_jobs == 0
                and idle_for >= settings.whisper_idle_seconds
                and await mac_whisper.available()
            ):
                stopped = await self.stop_mac_whisper()

                if stopped:
                    async with self.state_lock:
                        self.last_mac_use = 0.0

    async def runtime_status(self) -> tuple[int, int | None, str | None]:
        async with self.state_lock:
            active_jobs = self.active_mac_jobs
            last_use = self.last_mac_use
            active_backend = self.active_backend

        idle_seconds = (
            max(0, int(time.time() - last_use))
            if last_use > 0
            else None
        )

        return active_jobs, idle_seconds, active_backend


whisper_service = WhisperService()
