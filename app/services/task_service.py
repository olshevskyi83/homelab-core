from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.models.task import TaskCreate
from app.models.task import TaskResponse
from app.models.task import TaskStatus
from app.storage.database import PRIORITY_ORDER_SQL
from app.storage.database import connect
from app.storage.database import encode_json
from app.storage.database import row_to_task


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def create_task(task: TaskCreate) -> TaskResponse:
    task_id = str(uuid4())
    now = utc_now()

    database = await connect()

    try:
        await database.execute(
            """
            INSERT INTO tasks (
                id,
                created_at,
                updated_at,
                type,
                provider,
                status,
                priority,
                payload,
                result,
                error,
                attempts,
                max_attempts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?)
            """,
            (
                task_id,
                now,
                now,
                task.type.value,
                task.provider.value,
                TaskStatus.WAITING.value,
                task.priority.value,
                encode_json(task.payload),
                task.max_attempts,
            ),
        )

        await database.commit()
        return await _read_task(database, task_id)

    finally:
        await database.close()


async def _read_task(
    database,
    task_id: str,
) -> TaskResponse:
    cursor = await database.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise RuntimeError(f"Task {task_id} was not found")

    return TaskResponse.model_validate(row_to_task(row))


async def get_task(task_id: str) -> TaskResponse | None:
    database = await connect()

    try:
        cursor = await database.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return TaskResponse.model_validate(row_to_task(row))

    finally:
        await database.close()


async def list_tasks(
    *,
    status: TaskStatus | None = None,
    task_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TaskResponse], int]:
    conditions: list[str] = []
    parameters: list[Any] = []

    if status is not None:
        conditions.append("status = ?")
        parameters.append(status.value)

    if task_type is not None:
        conditions.append("type = ?")
        parameters.append(task_type)

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )

    database = await connect()

    try:
        count_cursor = await database.execute(
            f"SELECT COUNT(*) AS count FROM tasks {where_clause}",
            parameters,
        )
        count_row = await count_cursor.fetchone()
        total = int(count_row["count"]) if count_row else 0

        cursor = await database.execute(
            f"""
            SELECT *
            FROM tasks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            OFFSET ?
            """,
            [*parameters, limit, offset],
        )

        rows = await cursor.fetchall()

        tasks = [
            TaskResponse.model_validate(row_to_task(row))
            for row in rows
        ]

        return tasks, total

    finally:
        await database.close()


async def cancel_task(task_id: str) -> TaskResponse | None:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?, error = NULL
            WHERE id = ? AND status = ?
            """,
            (
                TaskStatus.CANCELLED.value,
                utc_now(),
                task_id,
                TaskStatus.WAITING.value,
            ),
        )

        await database.commit()

        if cursor.rowcount == 0:
            return None

        return await _read_task(database, task_id)

    finally:
        await database.close()


async def retry_task(task_id: str) -> TaskResponse | None:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                result = NULL,
                error = NULL
            WHERE
                id = ?
                AND status IN (?, ?)
                AND attempts < max_attempts
            """,
            (
                TaskStatus.WAITING.value,
                utc_now(),
                task_id,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ),
        )

        await database.commit()

        if cursor.rowcount == 0:
            return None

        return await _read_task(database, task_id)

    finally:
        await database.close()


async def claim_next_task(
    task_type: str,
) -> TaskResponse | None:
    database = await connect()

    try:
        await database.execute("BEGIN IMMEDIATE")

        cursor = await database.execute(
            f"""
            SELECT *
            FROM tasks
            WHERE
                status = ?
                AND type = ?
                AND attempts < max_attempts
            ORDER BY
                {PRIORITY_ORDER_SQL} DESC,
                created_at ASC
            LIMIT 1
            """,
            (
                TaskStatus.WAITING.value,
                task_type,
            ),
        )

        row = await cursor.fetchone()

        if row is None:
            await database.rollback()
            return None

        update_cursor = await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                attempts = attempts + 1
            WHERE id = ? AND status = ?
            """,
            (
                TaskStatus.RUNNING.value,
                utc_now(),
                row["id"],
                TaskStatus.WAITING.value,
            ),
        )

        if update_cursor.rowcount != 1:
            await database.rollback()
            return None

        await database.commit()
        return await _read_task(database, row["id"])

    except Exception:
        await database.rollback()
        raise

    finally:
        await database.close()


async def complete_task(
    task_id: str,
    result: dict[str, Any],
) -> TaskResponse:
    database = await connect()

    try:
        await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                result = ?,
                error = NULL
            WHERE id = ? AND status = ?
            """,
            (
                TaskStatus.COMPLETED.value,
                utc_now(),
                encode_json(result),
                task_id,
                TaskStatus.RUNNING.value,
            ),
        )

        await database.commit()
        return await _read_task(database, task_id)

    finally:
        await database.close()


async def postpone_task(
    task_id: str,
    error: str,
) -> TaskResponse:
    database = await connect()

    try:
        await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                error = ?
            WHERE id = ? AND status = ?
            """,
            (
                TaskStatus.WAITING.value,
                utc_now(),
                error[:4000],
                task_id,
                TaskStatus.RUNNING.value,
            ),
        )

        await database.commit()
        return await _read_task(database, task_id)

    finally:
        await database.close()


async def fail_task(
    task_id: str,
    error: str,
) -> TaskResponse:
    database = await connect()

    try:
        await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                error = ?
            WHERE id = ? AND status = ?
            """,
            (
                TaskStatus.FAILED.value,
                utc_now(),
                error[:4000],
                task_id,
                TaskStatus.RUNNING.value,
            ),
        )

        await database.commit()
        return await _read_task(database, task_id)

    finally:
        await database.close()


async def recover_interrupted_tasks() -> int:
    """
    After a container restart, return unfinished running tasks
    to the waiting state.
    """
    database = await connect()

    try:
        cursor = await database.execute(
            """
            UPDATE tasks
            SET
                status = ?,
                updated_at = ?,
                error = 'Worker interrupted; task returned to queue'
            WHERE status = ?
            """,
            (
                TaskStatus.WAITING.value,
                utc_now(),
                TaskStatus.RUNNING.value,
            ),
        )

        await database.commit()
        return cursor.rowcount

    finally:
        await database.close()


async def get_stats() -> dict[str, int]:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM tasks
            GROUP BY status
            """
        )
        rows = await cursor.fetchall()

        counters = {
            status.value: 0
            for status in TaskStatus
        }

        for row in rows:
            counters[row["status"]] = int(row["count"])

        return {
            "total": sum(counters.values()),
            "waiting": counters[TaskStatus.WAITING.value],
            "running": counters[TaskStatus.RUNNING.value],
            "completed": counters[TaskStatus.COMPLETED.value],
            "failed": counters[TaskStatus.FAILED.value],
            "cancelled": counters[TaskStatus.CANCELLED.value],
        }

    finally:
        await database.close()
