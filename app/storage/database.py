import json
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import settings
from app.storage.migrations import run_migrations


PRIORITY_ORDER_SQL = """
CASE priority
    WHEN 'critical' THEN 4
    WHEN 'high' THEN 3
    WHEN 'normal' THEN 2
    WHEN 'low' THEN 1
    ELSE 0
END
"""


async def connect() -> aiosqlite.Connection:
    database_path = Path(settings.database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    database = await aiosqlite.connect(database_path)
    database.row_factory = aiosqlite.Row

    await database.execute("PRAGMA journal_mode=WAL")
    await database.execute("PRAGMA foreign_keys=ON")
    await database.execute("PRAGMA busy_timeout=5000")

    return database


async def initialize_database() -> int:
    database = await connect()

    try:
        return await run_migrations(database)
    finally:
        await database.close()


async def get_schema_version() -> int:
    database = await connect()

    try:
        cursor = await database.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM schema_migrations
            """
        )

        row = await cursor.fetchone()

        return int(row["version"]) if row else 0

    finally:
        await database.close()


def encode_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_json(value: str | None) -> Any:
    if value is None:
        return None

    return json.loads(value)


def row_to_task(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "type": row["type"],
        "provider": row["provider"],
        "status": row["status"],
        "priority": row["priority"],
        "payload": decode_json(row["payload"]),
        "result": decode_json(row["result"]),
        "error": row["error"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
    }
