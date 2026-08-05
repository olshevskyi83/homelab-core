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

Interactive API documentation:
http://homelab:3010/docs

Installation
cp .env.example .env
nano .env
docker compose up -d --build

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
