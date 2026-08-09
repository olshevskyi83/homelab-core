# Homelab Core

Homelab Core is a local AI orchestration platform for a Fujitsu server and a Mac compute node.

## Architecture

```text
Homepage / Open WebUI / n8n
              |
              v
        Homelab Core
        |     |     |
        |     |     +-- Persistent task queue
        |     +-------- Resource and model managers
        +-------------- Whisper and LLM routing
              |
      +-------+--------+
      |                |
      v                v
  Fujitsu          Mac compute node
  Whisper CPU      LM Studio
  LiteLLM          MLX Whisper
  Qdrant           Mac Agent
Main features

* OpenAI-compatible LLM routing through LiteLLM
* Persistent SQLite task queue
* Deferred LLM execution while the Mac is offline
* Automatic Mac Whisper startup
* Automatic Whisper shutdown after inactivity
* Fujitsu Whisper fallback
* Resource policy for 24 GB Mac memory
* Dashboard, health and model APIs
* Structured JSON logging
* Database migrations
* Smoke-test script

Main endpoints
GET  /
GET  /health
GET  /dashboard
GET  /system
GET  /models
GET  /resources/mac
GET  /tasks
POST /tasks
POST /v1/audio/transcriptions
POST /knowledge/documents
GET  /knowledge/documents/{document_id}
GET  /knowledge/documents/{document_id}/status
POST /knowledge/documents/{document_id}/index
POST /knowledge/documents/{document_id}/reindex
DELETE /knowledge/documents/{document_id}/index
DELETE /knowledge/documents/{document_id}

Interactive API documentation:
http://homelab:3010/docs

Open WebUI can use Homelab Knowledge as an OpenAI-compatible model through:

```text
GET  /v1/models
POST /v1/chat/completions
models:
  homelab-knowledge  (all indexed sources)
  homelab-audio      (Audio Lab only)
  homelab-documents  (Document Lab only)
```

The adapter searches the central Qdrant collection, sends the retrieved
context and conversation history to `KNOWLEDGE_CHAT_MODEL`, and includes the
matched source filenames in the assistant response. It does not create a
second Open WebUI Knowledge index.

Installation
cp .env.example .env
nano .env
docker compose up -d --build

Document Lab files are registered by absolute path or by a path relative to
`DOCUMENTS_ROOT`. By default the host directory
`/home/homelabuser/RemoteDrop/Documents` is mounted read-only at `/documents`
inside Homelab Core.

`DELETE /knowledge/documents/{document_id}` is the source-agnostic removal
operation for every Knowledge client. It deletes the document's vectors and
records status `deleted`, but never deletes the source file owned by Audio Lab,
Document Lab, or another ingestion application. Use the `/index` variant when
the document should remain registered and available for reindexing.

The external Docker network must already exist:
docker network create ai-network

Smoke test
./scripts/smoke_test.sh

Or, when installed globally:
homelab-ai-test

Security

Never commit:

* .env
* API tokens
* SQLite databases
* logs
* model files

Version

Current stable foundation: v1.0.0
