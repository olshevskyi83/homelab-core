import asyncio
import logging

import httpx

from app.config import settings
from app.providers import litellm
from app.providers import lm_studio
from app.services import task_service
from app.services.resource_manager import can_run_mac_llm


logger = logging.getLogger("homelab.llm_worker")


class LLMWorker:
    def __init__(self) -> None:
        self.backend_online: bool | None = None

    def log_backend_state(self, online: bool) -> None:
        if online == self.backend_online:
            return

        self.backend_online = online

        logger.info(
            "LLM backend state changed",
            extra={
                "event": "llm_backend_state",
                "online": online,
            },
        )

    async def run(self) -> None:
        logger.info(
            "LLM worker started",
            extra={
                "event": "worker_started",
                "worker": "llm",
                "poll_seconds": (
                    settings.task_worker_poll_seconds
                ),
            },
        )

        while True:
            try:
                await self.process_one()

            except asyncio.CancelledError:
                logger.info(
                    "LLM worker stopped",
                    extra={
                        "event": "worker_stopped",
                        "worker": "llm",
                    },
                )
                raise

            except Exception:
                logger.exception(
                    "Unexpected LLM worker loop error",
                    extra={
                        "event": "worker_loop_error",
                        "worker": "llm",
                    },
                )

            await asyncio.sleep(
                settings.task_worker_poll_seconds
            )

    async def process_one(self) -> None:
        litellm_ok, lm_studio_ok = await asyncio.gather(
            litellm.available(),
            lm_studio.available(),
        )

        resource_decision = await can_run_mac_llm()

        backend_online = (
            litellm_ok
            and lm_studio_ok
            and resource_decision.allowed
        )

        self.log_backend_state(backend_online)

        if not backend_online:
            return

        task = await task_service.claim_next_task("llm")

        if task is None:
            return

        logger.info(
            "LLM task claimed",
            extra={
                "event": "task_claimed",
                "worker": "llm",
                "task_id": task.id,
                "task_type": task.type.value,
                "priority": task.priority.value,
                "attempt": task.attempts,
                "max_attempts": task.max_attempts,
                "model": task.payload.get("model"),
            },
        )

        try:
            payload = dict(task.payload)

            if "model" not in payload:
                raise ValueError(
                    "LLM task payload must contain 'model'"
                )

            if "messages" not in payload:
                raise ValueError(
                    "LLM task payload must contain 'messages'"
                )

            payload["stream"] = False
            result = await litellm.chat_completion(payload)

            await task_service.complete_task(
                task.id,
                result,
            )

            usage = result.get("usage") or {}

            logger.info(
                "LLM task completed",
                extra={
                    "event": "task_completed",
                    "worker": "llm",
                    "task_id": task.id,
                    "model": result.get("model"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get(
                        "completion_tokens"
                    ),
                    "total_tokens": usage.get("total_tokens"),
                },
            )

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if task.attempts >= task.max_attempts:
                await task_service.fail_task(
                    task.id,
                    f"LLM backend unavailable: {exc}",
                )
                event = "task_failed"
                status = "failed"
            else:
                await task_service.postpone_task(
                    task.id,
                    f"LLM backend temporarily unavailable: {exc}",
                )
                event = "task_postponed"
                status = "waiting"

            logger.warning(
                "LLM backend unavailable during task",
                extra={
                    "event": event,
                    "worker": "llm",
                    "task_id": task.id,
                    "task_status": status,
                    "error": str(exc),
                },
            )

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            detail = exc.response.text[:2000]

            if (
                status_code >= 500
                and task.attempts < task.max_attempts
            ):
                await task_service.postpone_task(
                    task.id,
                    f"LiteLLM HTTP {status_code}: {detail}",
                )
                event = "task_postponed"
                task_status = "waiting"
            else:
                await task_service.fail_task(
                    task.id,
                    f"LiteLLM HTTP {status_code}: {detail}",
                )
                event = "task_failed"
                task_status = "failed"

            logger.warning(
                "LiteLLM returned an error",
                extra={
                    "event": event,
                    "worker": "llm",
                    "task_id": task.id,
                    "task_status": task_status,
                    "http_status": status_code,
                    "error": detail,
                },
            )

        except (ValueError, TypeError) as exc:
            await task_service.fail_task(
                task.id,
                str(exc),
            )

            logger.warning(
                "Invalid LLM task",
                extra={
                    "event": "task_failed",
                    "worker": "llm",
                    "task_id": task.id,
                    "task_status": "failed",
                    "error": str(exc),
                },
            )

        except Exception as exc:
            logger.exception(
                "Unexpected LLM task error",
                extra={
                    "event": "task_error",
                    "worker": "llm",
                    "task_id": task.id,
                    "error": str(exc),
                },
            )

            if task.attempts >= task.max_attempts:
                await task_service.fail_task(
                    task.id,
                    f"Unexpected worker error: {exc}",
                )
            else:
                await task_service.postpone_task(
                    task.id,
                    f"Unexpected temporary error: {exc}",
                )


llm_worker = LLMWorker()
