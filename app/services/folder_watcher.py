import asyncio
import logging
import shutil
import time
from pathlib import Path

from app.config import settings
from app.models.task import (
    TaskCreate,
    TaskPriority,
    TaskProvider,
    TaskType,
)
from app.services import task_service


logger = logging.getLogger("homelab.folder_watcher")


SUPPORTED_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


class FolderWatcher:
    def __init__(self) -> None:
        self.seen_state: dict[Path, tuple[int, float, float]] = {}

    async def run(self) -> None:
        self.ensure_directories()

        logger.info(
            "Audio folder watcher started",
            extra={
                "event": "worker_started",
                "worker": "folder_watcher",
                "poll_seconds": settings.audio_watcher_poll_seconds,
                "settle_seconds": settings.audio_file_settle_seconds,
            },
        )

        while True:
            try:
                await self.scan_once()

            except asyncio.CancelledError:
                logger.info(
                    "Audio folder watcher stopped",
                    extra={
                        "event": "worker_stopped",
                        "worker": "folder_watcher",
                    },
                )
                raise

            except Exception:
                logger.exception(
                    "Unexpected folder watcher error",
                    extra={
                        "event": "worker_loop_error",
                        "worker": "folder_watcher",
                    },
                )

            await asyncio.sleep(settings.audio_watcher_poll_seconds)

    def ensure_directories(self) -> None:
        root = Path(settings.audio_root)

        for name in (
            "incoming",
            "processing",
            "ready",
            "failed",
            "archive",
        ):
            (root / name).mkdir(parents=True, exist_ok=True)

    async def scan_once(self) -> None:
        incoming = Path(settings.audio_root) / "incoming"

        current_files = {
            path
            for path in incoming.iterdir()
            if path.is_file() and not path.name.startswith(".")
        }

        # Remove entries for files that disappeared.
        for path in list(self.seen_state):
            if path not in current_files:
                self.seen_state.pop(path, None)

        for source in sorted(current_files):
            if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
                await self.reject_unsupported(source)
                continue

            if not self.file_is_settled(source):
                continue

            await self.enqueue_file(source)

    def file_is_settled(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False

        now = time.monotonic()
        current = (stat.st_size, stat.st_mtime)

        previous = self.seen_state.get(path)

        if previous is None:
            self.seen_state[path] = (
                stat.st_size,
                stat.st_mtime,
                now,
            )
            return False

        previous_size, previous_mtime, stable_since = previous

        if (
            previous_size != current[0]
            or previous_mtime != current[1]
        ):
            self.seen_state[path] = (
                stat.st_size,
                stat.st_mtime,
                now,
            )
            return False

        return (
            now - stable_since
            >= settings.audio_file_settle_seconds
        )

    async def enqueue_file(self, source: Path) -> None:
        processing_dir = Path(settings.audio_root) / "processing"
        destination = self.unique_destination(
            processing_dir / source.name
        )

        try:
            shutil.move(str(source), str(destination))
            self.seen_state.pop(source, None)

            task = await task_service.create_task(
                TaskCreate(
                    type=TaskType.WHISPER,
                    provider=TaskProvider.AUTO,
                    priority=TaskPriority.NORMAL,
                    payload={
                        "file_path": str(destination),
                        "language": "auto",
                        "source": "folder_watcher",
                        "original_filename": source.name,
                    },
                    max_attempts=3,
                )
            )

            logger.info(
                "Audio file queued",
                extra={
                    "event": "audio_file_queued",
                    "worker": "folder_watcher",
                    "task_id": task.id,
                    "source_file": source.name,
                    "processing_file": str(destination),
                },
            )

        except Exception:
            logger.exception(
                "Could not queue audio file",
                extra={
                    "event": "audio_queue_error",
                    "worker": "folder_watcher",
                    "source_file": str(source),
                },
            )

            # If move succeeded but task creation failed,
            # return the file to incoming when possible.
            if destination.exists() and not source.exists():
                rollback = self.unique_destination(
                    source.parent / destination.name
                )

                try:
                    shutil.move(
                        str(destination),
                        str(rollback),
                    )
                except OSError:
                    logger.exception(
                        "Could not return file to incoming",
                        extra={
                            "event": "audio_rollback_error",
                            "source_file": str(destination),
                        },
                    )

    async def reject_unsupported(self, source: Path) -> None:
        failed_dir = Path(settings.audio_root) / "failed"
        destination = self.unique_destination(
            failed_dir / source.name
        )

        try:
            shutil.move(str(source), str(destination))
            self.seen_state.pop(source, None)

            reason_file = destination.with_name(
                destination.name + ".error.txt"
            )
            reason_file.write_text(
                (
                    "Unsupported audio/video file extension: "
                    f"{source.suffix or '[none]'}\n"
                ),
                encoding="utf-8",
            )

            logger.warning(
                "Unsupported file moved to failed",
                extra={
                    "event": "unsupported_audio_file",
                    "worker": "folder_watcher",
                    "source_file": source.name,
                    "failed_file": str(destination),
                },
            )

        except OSError:
            logger.exception(
                "Could not move unsupported file",
                extra={
                    "event": "unsupported_file_move_error",
                    "source_file": str(source),
                },
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


folder_watcher = FolderWatcher()
