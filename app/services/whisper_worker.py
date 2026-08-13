import asyncio
import json
import logging
import mimetypes
import shutil
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services import task_service
from app.services.whisper_service import whisper_service


logger = logging.getLogger("homelab.whisper_worker")


class WhisperWorker:
    async def run(self) -> None:
        logger.info(
            "Whisper worker started",
            extra={
                "event": "worker_started",
                "worker": "whisper",
                "poll_seconds": settings.whisper_worker_poll_seconds,
            },
        )

        while True:
            try:
                await self.process_one()

            except asyncio.CancelledError:
                logger.info(
                    "Whisper worker stopped",
                    extra={
                        "event": "worker_stopped",
                        "worker": "whisper",
                    },
                )
                raise

            except Exception:
                logger.exception(
                    "Unexpected Whisper worker loop error",
                    extra={
                        "event": "worker_loop_error",
                        "worker": "whisper",
                    },
                )

            await asyncio.sleep(
                settings.whisper_worker_poll_seconds
            )

    async def process_one(self) -> None:
        task = await task_service.claim_next_task("whisper")

        if task is None:
            return

        logger.info(
            "Whisper task claimed",
            extra={
                "event": "task_claimed",
                "worker": "whisper",
                "task_id": task.id,
                "attempt": task.attempts,
                "max_attempts": task.max_attempts,
            },
        )

        try:
            source_path = self.resolve_source_path(task.payload)
            self.validate_source(source_path)

            language = task.payload.get("language")
            prompt = task.payload.get("prompt")

            fields: dict[str, str] = {
                "response_format": "json",
            }

            if language and language != "auto":
                fields["language"] = str(language)

            if prompt:
                fields["prompt"] = str(prompt)

            audio = source_path.read_bytes()

            response = await whisper_service.transcribe(
                filename=source_path.name,
                content=audio,
                content_type=(
                    mimetypes.guess_type(source_path.name)[0]
                    or "application/octet-stream"
                ),
                fields=fields,
                track_active_backend=True,
            )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Whisper HTTP {response.status_code}: "
                    f"{response.text[:2000]}"
                )

            result = self.decode_response(response)

            output_files = self.write_results(
                source_path=source_path,
                task_id=task.id,
                result=result,
            )

            archived_file = self.archive_source(source_path)

            completion_result = {
                "text": result.get("text", ""),
                "source_file": str(source_path),
                "archived_file": str(archived_file),
                "output_files": output_files,
            }

            await task_service.complete_task(
                task.id,
                completion_result,
            )

            logger.info(
                "Whisper task completed",
                extra={
                    "event": "task_completed",
                    "worker": "whisper",
                    "task_id": task.id,
                    "source_file": source_path.name,
                    "archived_file": str(archived_file),
                },
            )

        except (
            httpx.ConnectError,
            httpx.TimeoutException,
        ) as exc:
            await self.handle_transient_error(task, exc)

        except Exception as exc:
            await self.handle_task_error(task, exc)

    def resolve_source_path(
        self,
        payload: dict[str, Any],
    ) -> Path:
        raw_path = payload.get("file_path")

        if not raw_path:
            raise ValueError(
                "Whisper task payload must contain 'file_path'"
            )

        path = Path(str(raw_path)).resolve()
        audio_root = Path(settings.audio_root).resolve()

        if path != audio_root and audio_root not in path.parents:
            raise ValueError(
                "file_path is outside the configured Audio root"
            )

        return path

    @staticmethod
    def validate_source(path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"Audio file does not exist: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Audio path is not a file: {path}"
            )

        if path.stat().st_size == 0:
            raise ValueError(
                f"Audio file is empty: {path}"
            )

    @staticmethod
    def decode_response(
        response: httpx.Response,
    ) -> dict[str, Any]:
        try:
            payload = response.json()

            if isinstance(payload, dict):
                return payload

            return {
                "text": str(payload),
            }

        except ValueError:
            return {
                "text": response.text,
            }

    def write_results(
        self,
        *,
        source_path: Path,
        task_id: str,
        result: dict[str, Any],
    ) -> list[str]:
        ready_dir = Path(settings.audio_root) / "ready"
        ready_dir.mkdir(parents=True, exist_ok=True)

        base_name = self.unique_output_stem(
            ready_dir,
            source_path.stem,
        )

        txt_path = ready_dir / f"{base_name}.txt"
        json_path = ready_dir / f"{base_name}.json"

        text = str(result.get("text", "")).strip()

        txt_path.write_text(
            text + ("\n" if text else ""),
            encoding="utf-8",
        )

        json_payload = {
            "task_id": task_id,
            "source_filename": source_path.name,
            "transcription": result,
        }

        json_path.write_text(
            json.dumps(
                json_payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return [
            str(txt_path),
            str(json_path),
        ]

    def archive_source(
        self,
        source_path: Path,
    ) -> Path:
        archive_dir = Path(settings.audio_root) / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        destination = self.unique_destination(
            archive_dir / source_path.name
        )

        shutil.move(
            str(source_path),
            str(destination),
        )

        return destination

    async def handle_transient_error(
        self,
        task,
        error: Exception,
    ) -> None:
        message = f"Whisper backend temporarily unavailable: {error}"

        if task.attempts >= task.max_attempts:
            await task_service.fail_task(
                task.id,
                message,
            )
            self.move_to_failed(task.payload)

            event = "task_failed"
        else:
            await task_service.postpone_task(
                task.id,
                message,
            )
            event = "task_postponed"

        logger.warning(
            "Whisper backend unavailable",
            extra={
                "event": event,
                "worker": "whisper",
                "task_id": task.id,
                "error": str(error),
            },
        )

    async def handle_task_error(
        self,
        task,
        error: Exception,
    ) -> None:
        message = str(error)

        retryable = isinstance(
            error,
            RuntimeError,
        )

        if retryable and task.attempts < task.max_attempts:
            await task_service.postpone_task(
                task.id,
                message,
            )
            event = "task_postponed"
        else:
            await task_service.fail_task(
                task.id,
                message,
            )
            self.move_to_failed(task.payload)
            event = "task_failed"

        logger.warning(
            "Whisper task error",
            extra={
                "event": event,
                "worker": "whisper",
                "task_id": task.id,
                "error": message,
            },
        )

    def move_to_failed(
        self,
        payload: dict[str, Any],
    ) -> None:
        raw_path = payload.get("file_path")

        if not raw_path:
            return

        source_path = Path(str(raw_path))

        if not source_path.exists() or not source_path.is_file():
            return

        failed_dir = Path(settings.audio_root) / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)

        destination = self.unique_destination(
            failed_dir / source_path.name
        )

        shutil.move(
            str(source_path),
            str(destination),
        )

    @staticmethod
    def unique_destination(path: Path) -> Path:
        if not path.exists():
            return path

        counter = 1

        while True:
            candidate = path.with_name(
                f"{path.stem}_{counter}{path.suffix}"
            )

            if not candidate.exists():
                return candidate

            counter += 1

    @staticmethod
    def unique_output_stem(
        directory: Path,
        stem: str,
    ) -> str:
        candidate = stem
        counter = 1

        while (
            (directory / f"{candidate}.txt").exists()
            or (directory / f"{candidate}.json").exists()
        ):
            candidate = f"{stem}_{counter}"
            counter += 1

        return candidate


whisper_worker = WhisperWorker()
