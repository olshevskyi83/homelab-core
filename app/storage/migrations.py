from collections.abc import Awaitable, Callable

import aiosqlite


MigrationFunction = Callable[[aiosqlite.Connection], Awaitable[None]]


async def migration_1(database: aiosqlite.Connection) -> None:
    """
    Initial task queue schema.
    """
    await database.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            type TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,

            payload TEXT NOT NULL,
            result TEXT,
            error TEXT,

            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status
        ON tasks(status);

        CREATE INDEX IF NOT EXISTS idx_tasks_queue_order
        ON tasks(status, priority, created_at);

        CREATE INDEX IF NOT EXISTS idx_tasks_type
        ON tasks(type);
        """
    )


async def migration_2(database: aiosqlite.Connection) -> None:
    """
    Knowledge-document indexing state for Qdrant.
    """
    await database.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            document_id TEXT PRIMARY KEY,
            task_id TEXT UNIQUE,
            source_type TEXT NOT NULL,
            project TEXT NOT NULL,
            source_filename TEXT,
            text_path TEXT,

            index_status TEXT NOT NULL DEFAULT 'not_indexed',
            chunk_count INTEGER NOT NULL DEFAULT 0,
            embedding_model TEXT,
            collection_name TEXT,

            indexed_at TEXT,
            updated_at TEXT NOT NULL,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status
        ON knowledge_documents(index_status);

        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source_type
        ON knowledge_documents(source_type);
        """
    )


MIGRATIONS: dict[int, MigrationFunction] = {
    1: migration_1,
    2: migration_2,
}


async def ensure_migration_table(
    database: aiosqlite.Connection,
) -> None:
    await database.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def get_current_version(
    database: aiosqlite.Connection,
) -> int:
    cursor = await database.execute(
        """
        SELECT COALESCE(MAX(version), 0) AS version
        FROM schema_migrations
        """
    )

    row = await cursor.fetchone()

    return int(row["version"]) if row else 0


async def run_migrations(
    database: aiosqlite.Connection,
) -> int:
    await ensure_migration_table(database)

    current_version = await get_current_version(database)

    for version in sorted(MIGRATIONS):
        if version <= current_version:
            continue

        migration = MIGRATIONS[version]

        try:
            await database.execute("BEGIN IMMEDIATE")
            await migration(database)

            await database.execute(
                """
                INSERT INTO schema_migrations (version)
                VALUES (?)
                """,
                (version,),
            )

            await database.commit()

        except Exception:
            await database.rollback()
            raise

    return await get_current_version(database)
