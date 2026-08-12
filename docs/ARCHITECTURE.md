# Homelab Core Architecture

## Scope and evidence

This document describes behavior confirmed by the current repository. Its
sources are the Python application, `Dockerfile`, `docker-compose.yml`,
`.env.example`, and `README.md`. It does not claim that an external service is
deployed or configured merely because the application has an integration for
it.

## Architectural invariants

- Homelab Core is the single owner of the Knowledge API, Qdrant integration,
  and RAG flow.
- Audio Lab and Document Lab are ingestion clients of that central Knowledge
  capability.
- Open WebUI is the central chat client and uses the OpenAI-compatible model
  ID `homelab-knowledge`.
- Homelab Core uses one Knowledge collection, selected by
  `QDRANT_COLLECTION` and defaulted to `homelab_knowledge`.
- Audio and document content are not separated into different Knowledge
  databases or collections.
- `source_type` and `project` are Qdrant payload metadata and optional search
  filters. They do not create independent indexes.
- Knowledge deletion removes vectors and changes stored Knowledge state; it
  never deletes the source file.
- The active ASGI entrypoint is `app.main:app`.
- The repository-root `app.py` is legacy and is not part of the current Docker
  runtime: the Dockerfile copies `app/` and starts `app.main:app`.

## Runtime structure

The Docker image starts Uvicorn on container port `8080`. `app/main.py`
creates a FastAPI application named `Homelab Core`, version `1.5.0`, includes
the routers under `app/api/`, initializes the SQLite schema, recovers
interrupted tasks, and starts four asynchronous background loops:

- the Whisper idle watcher;
- the LLM worker;
- the Whisper worker;
- the audio folder watcher.

The Compose service is named `ai-gateway`, publishes host port `3010` to
container port `8080`, and joins the external `ai-network` network.

## Persistent state and mounted sources

The application stores its queue and Knowledge document state in SQLite. The
default `DATABASE_PATH` is `/app/data/queue.db`; Compose mounts repository-local
`./data` at `/app/data`.

Compose mounts these server paths:

| Server path | Container path | Mode | Confirmed use |
| --- | --- | --- | --- |
| `/home/homelabuser/RemoteDrop/Audio` | `/remote/Audio` | read/write | Audio folder watcher and transcription output flow |
| `/home/homelabuser/RemoteDrop/Documents` | `/documents` | read-only | Document registration and indexing source files |

Document paths are resolved within `DOCUMENTS_ROOT`. Relative paths are
joined to that root; absolute paths are accepted only when they still resolve
inside it. Audio transcription text used for indexing is similarly checked
against `AUDIO_ROOT`. The explicit Audio session transcript endpoint,
`POST /knowledge/transcriptions`, accepts only a relative `text_path` and
resolves it strictly below `AUDIO_ROOT`; absolute paths, parent traversal, and
symlink escapes are rejected. It fixes `source_type=transcription` and
`project=audio-lab`, so neither root nor metadata is selected by the client.

## Ingestion and Knowledge lifecycle

### Audio Lab

The folder watcher observes `AUDIO_ROOT/incoming`, waits for supported files
to settle, moves them to `processing`, and creates Whisper tasks.

In the current implementation, each completed Whisper transcription with a
text output receives a separate Knowledge registration with:

- `document_id` equal to the task ID;
- `source_type` set to `transcription`;
- `project` set to `audio-lab`.

This task-level representation is current implementation detail, not an
immutable architectural rule. The ingestion representation may evolve while
Homelab Core remains the owner of Knowledge. No alternative or session-level
representation is implemented or claimed here.

The `/audio-lab` routes provide an Audio Lab-oriented view and indexing
operations over the same central Knowledge service.

### Document Lab

Document Lab uses `POST /knowledge/documents` to register a file within
`DOCUMENTS_ROOT`. Defaults in the request model are:

- `source_type`: `document`;
- `project`: `document-lab`.

The client may supply another non-empty value for either metadata field. If no
`document_id` is supplied, Homelab Core derives a stable UUID from the resolved
file path.

### Audio session transcription ingestion

Audio Lab can register one assembled session transcript through
`POST /knowledge/transcriptions` with a stable session-derived `document_id`,
a human-readable `source_filename`, and a relative path below `AUDIO_ROOT`.
Repeated registration of the same ID updates the same registry record rather
than creating another document. This explicit contract does not change the
current task-per-transcription implementation described above.

### Indexing

Homelab Core reads the registered text, normalizes whitespace, splits it using
`KNOWLEDGE_CHUNK_SIZE` and `KNOWLEDGE_CHUNK_OVERLAP`, and requests embeddings
through the LiteLLM provider using `EMBEDDING_MODEL`.

The Qdrant collection is created on demand with cosine distance when it does
not exist. Every point includes `document_id`, chunk position, source
filename, `source_type`, `project`, text, and embedding-model metadata.
Reindexing deletes that document's existing points before upserting the new
points, so it is replacement rather than duplication.

### Search and RAG

Knowledge search embeds the query and performs grouped Qdrant retrieval by
`document_id`. The implementation asks for up to two hits per group and
interleaves group results, limiting domination by one large source. Optional
`source_type`, `project`, and score-threshold filters are applied to retrieval.

Knowledge chat supplies retrieved context to the configured
`KNOWLEDGE_CHAT_MODEL`. The raw `/knowledge/chat` response retains retrieved
sources. The OpenAI-compatible adapter exposes the fixed model ID
`homelab-knowledge` and appends only sources cited by the generated answer when
the answer contains numbered source citations.

### Delete semantics

`DELETE /knowledge/documents/{document_id}/index` deletes the document's
Qdrant points and returns its state to `not_indexed`, leaving the registration
available for reindexing.

`DELETE /knowledge/documents/{document_id}` deletes the same Qdrant points and
then physically removes the Knowledge registry row. It does not delete the
source file. A failed Qdrant deletion leaves the registry row intact. The
Audio Lab index-delete route uses the separate index-deletion service and does
not remove the registry row. Deprecated purge routes exist only to clean up
legacy rows that already have `index_status=deleted`.

## API routes

### Service and resource status

| Method | Path |
| --- | --- |
| `GET` | `/` |
| `GET` | `/health` |
| `GET` | `/dashboard` |
| `GET` | `/system` |
| `GET` | `/models` |
| `GET` | `/resources/mac` |
| `GET` | `/v1/llm/status` |
| `GET` | `/v1/embeddings/status` |

The two `/v1/*/status` routes currently report reserved functionality.

### Tasks and transcription

| Method | Path |
| --- | --- |
| `POST` | `/tasks` |
| `GET` | `/tasks` |
| `GET` | `/tasks/stats` |
| `GET` | `/tasks/{task_id}` |
| `POST` | `/tasks/{task_id}/cancel` |
| `POST` | `/tasks/{task_id}/retry` |
| `POST` | `/v1/audio/transcriptions` |

### Knowledge

| Method | Path |
| --- | --- |
| `POST` | `/knowledge/documents` |
| `POST` | `/knowledge/transcriptions` |
| `GET` | `/knowledge/documents/{document_id}` |
| `GET` | `/knowledge/documents/{document_id}/status` |
| `POST` | `/knowledge/documents/{document_id}/index` |
| `POST` | `/knowledge/documents/{document_id}/reindex` |
| `DELETE` | `/knowledge/documents/{document_id}/index` |
| `DELETE` | `/knowledge/documents/{document_id}` |
| `POST` | `/knowledge/search` |
| `POST` | `/knowledge/chat` |

### Audio Lab client view

| Method | Path |
| --- | --- |
| `GET` | `/audio-lab/tasks` |
| `POST` | `/audio-lab/tasks/{task_id}/index` |
| `POST` | `/audio-lab/tasks/{task_id}/reindex` |
| `DELETE` | `/audio-lab/tasks/{task_id}/index` |

### OpenAI-compatible Knowledge chat

| Method | Path |
| --- | --- |
| `GET` | `/v1/models` |
| `POST` | `/v1/chat/completions` |

FastAPI also supplies `/docs`, `/redoc`, and `/openapi.json` with its default
configuration.

## External integrations / not verified in this repository

The repository contains clients or configuration for Qdrant, LiteLLM, a
server Whisper endpoint, a Mac Agent, Mac Whisper, and LM Studio. README also
describes Open WebUI as a client of the OpenAI-compatible Knowledge model.
Their deployment definitions and live state are outside this repository and
were not verified for this document.

README mentions Homepage and n8n as possible consumers. No configuration for
them is present here, so they are not treated as confirmed components of the
repository-managed architecture.
