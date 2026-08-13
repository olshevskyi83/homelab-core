import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("MAC_AGENT_TOKEN", "test-token")

from app.services import dashboard_service
from app.services.whisper_service import WhisperService


class DashboardWhisperRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def build_dashboard(
        self,
        *,
        mac_data: dict | None,
        mac_running: bool,
        server_running: bool,
        active_backend: str | None = None,
    ):
        with (
            patch.object(
                dashboard_service.task_service,
                "get_stats",
                AsyncMock(
                    return_value={
                        "total": 0,
                        "waiting": 0,
                        "running": 0,
                        "completed": 0,
                        "failed": 0,
                        "cancelled": 0,
                    }
                ),
            ),
            patch.object(
                dashboard_service,
                "get_schema_version",
                AsyncMock(return_value=2),
            ),
            patch.object(
                dashboard_service.mac_agent,
                "health",
                AsyncMock(return_value=mac_data),
            ),
            patch.object(
                dashboard_service.litellm,
                "available",
                AsyncMock(return_value=True),
            ),
            patch.object(
                dashboard_service.lm_studio,
                "available",
                AsyncMock(return_value=True),
            ),
            patch.object(
                dashboard_service.mac_whisper,
                "available",
                AsyncMock(return_value=mac_running),
            ),
            patch.object(
                dashboard_service.server_whisper,
                "available",
                AsyncMock(return_value=server_running),
            ),
            patch.object(
                dashboard_service.whisper_service,
                "runtime_status",
                AsyncMock(return_value=(0, None, active_backend)),
            ),
        ):
            return await dashboard_service.build_dashboard()

    async def test_mac_available_while_mac_whisper_is_stopped(self) -> None:
        dashboard = await self.build_dashboard(
            mac_data={"hostname": "macbook"},
            mac_running=False,
            server_running=True,
        )

        self.assertTrue(dashboard.whisper.mac_available)
        self.assertFalse(dashboard.whisper.mac_running)
        self.assertTrue(dashboard.whisper.server_available)
        self.assertTrue(dashboard.whisper.server_running)
        self.assertIsNone(dashboard.whisper.active_backend)

    async def test_mac_unavailable(self) -> None:
        dashboard = await self.build_dashboard(
            mac_data=None,
            mac_running=False,
            server_running=True,
        )

        self.assertFalse(dashboard.whisper.mac_available)
        self.assertFalse(dashboard.whisper.mac_agent)

    async def test_server_unavailable(self) -> None:
        dashboard = await self.build_dashboard(
            mac_data={"hostname": "macbook"},
            mac_running=False,
            server_running=False,
        )

        self.assertFalse(dashboard.whisper.server_available)
        self.assertFalse(dashboard.whisper.server_running)

    async def test_existing_fields_remain_available(self) -> None:
        dashboard = await self.build_dashboard(
            mac_data={"hostname": "macbook"},
            mac_running=True,
            server_running=True,
            active_backend="mac",
        )

        self.assertTrue(dashboard.whisper.mac_agent)
        self.assertTrue(dashboard.whisper.mac_running)
        self.assertTrue(dashboard.whisper.server_running)
        self.assertEqual(dashboard.whisper.active_jobs, 0)


class WhisperActiveBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_mac_backend_is_active_only_during_task_execution(self) -> None:
        service = WhisperService()
        started = asyncio.Event()
        release = asyncio.Event()

        async def mac_transcribe(**_kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(status_code=200)

        with (
            patch.object(service, "ensure_mac_whisper", AsyncMock(return_value=True)),
            patch(
                "app.services.whisper_service.mac_whisper.transcribe",
                side_effect=mac_transcribe,
            ),
        ):
            task = asyncio.create_task(
                service.transcribe(
                    filename="lesson.wav",
                    content=b"audio",
                    content_type="audio/wav",
                    fields={},
                    track_active_backend=True,
                )
            )
            await started.wait()
            self.assertEqual((await service.runtime_status())[2], "mac")
            release.set()
            await task

        self.assertIsNone((await service.runtime_status())[2])

    async def test_server_fallback_is_active_only_during_task_execution(
        self,
    ) -> None:
        service = WhisperService()
        started = asyncio.Event()
        release = asyncio.Event()

        async def server_transcribe(**_kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(status_code=200)

        with (
            patch.object(service, "ensure_mac_whisper", AsyncMock(return_value=False)),
            patch(
                "app.services.whisper_service.server_whisper.transcribe",
                side_effect=server_transcribe,
            ),
        ):
            task = asyncio.create_task(
                service.transcribe(
                    filename="lesson.wav",
                    content=b"audio",
                    content_type="audio/wav",
                    fields={},
                    track_active_backend=True,
                )
            )
            await started.wait()
            self.assertEqual((await service.runtime_status())[2], "server")
            release.set()
            await task

        self.assertIsNone((await service.runtime_status())[2])

    async def test_active_backend_clears_after_provider_failure(self) -> None:
        service = WhisperService()

        with (
            patch.object(service, "ensure_mac_whisper", AsyncMock(return_value=False)),
            patch(
                "app.services.whisper_service.server_whisper.transcribe",
                AsyncMock(side_effect=httpx.ConnectError("unavailable")),
            ),
        ):
            with self.assertRaises(httpx.ConnectError):
                await service.transcribe(
                    filename="lesson.wav",
                    content=b"audio",
                    content_type="audio/wav",
                    fields={},
                    track_active_backend=True,
                )

        self.assertIsNone((await service.runtime_status())[2])
