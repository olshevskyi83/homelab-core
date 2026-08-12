# Homelab Core Deployment

## Scope

This document separates configuration tracked by Git from server-local
configuration and runtime data. It describes the current repository layout;
it does not assert that a deployment command has been executed successfully
on a particular server.

## Tracked repository configuration

The deployment-relevant tracked files are:

- `Dockerfile`: builds from `python:3.12-slim`, installs
  `requirements.txt`, copies `app/`, and starts
  `uvicorn app.main:app --host 0.0.0.0 --port 8080`;
- `docker-compose.yml`: defines the `ai-gateway` service, port mapping,
  volumes, environment-file reference, runtime user, restart policy, and
  external network;
- `.env.example`: documents the expected environment keys and non-secret
  example/default values;
- `requirements.txt`: defines Python dependencies.

Changes to these tracked files follow the normal review and explicit
commit/push approval workflow. The current Compose configuration uses:

```text
service:        ai-gateway
container:      ai-gateway
runtime user:   1000:1000
host port:      3010
container port: 8080
restart policy: unless-stopped
network:        ai-network (external)
```

The external network must already exist. Its lifecycle is not managed by this
Compose file.

## Server-local `.env`

Compose reads `.env` through `env_file`. This file is server-local, must not be
changed by automated repository work, and must never be committed or printed
in output. `.env.example` is the tracked inventory of expected keys, not a
production secret store.

The documented configuration groups are:

- Mac endpoints and credentials: `MAC_HOST`, `MAC_AGENT_PORT`,
  `MAC_WHISPER_PORT`, `MAC_AGENT_TOKEN`;
- Whisper backends and policy: `SERVER_WHISPER_URL`, `MAC_WHISPER_MODEL`,
  `SERVER_WHISPER_MODEL`, `WHISPER_IDLE_SECONDS`;
- LiteLLM: `LITELLM_URL`, `LITELLM_API_KEY`;
- queue and workers: `DATABASE_PATH`, `TASK_WORKER_POLL_SECONDS`,
  `WHISPER_WORKER_POLL_SECONDS`;
- Mac resource policy: `MAC_MEMORY_LIMIT_PERCENT`,
  `ALLOW_SIMULTANEOUS_MAC_AI`;
- ingestion paths and timing: `AUDIO_ROOT`, `DOCUMENTS_ROOT`,
  `AUDIO_WATCHER_POLL_SECONDS`, `AUDIO_FILE_SETTLE_SECONDS`;
- Knowledge and Qdrant: `QDRANT_URL`, `QDRANT_COLLECTION`,
  `EMBEDDING_MODEL`, `KNOWLEDGE_CHAT_MODEL`, `KNOWLEDGE_CHAT_LIMIT`,
  `KNOWLEDGE_CHUNK_SIZE`, `KNOWLEDGE_CHUNK_OVERLAP`.

`docker-compose.yml` explicitly sets `DOCUMENTS_ROOT=/documents` in the
service environment.

## Persistent data

Compose mounts repository-local `./data` at `/app/data`. With the documented
default `DATABASE_PATH=/app/data/queue.db`, the SQLite task queue and Knowledge
document state survive container replacement through that bind mount.

The contents of `./data` are runtime data, not tracked repository
configuration. SQLite records Knowledge state and collection metadata, while
the vectors themselves are held by the externally configured Qdrant service.

## RemoteDrop mounts

Compose declares two server-specific bind mounts:

| Server path | Container path | Access |
| --- | --- | --- |
| `/home/homelabuser/RemoteDrop/Audio` | `/remote/Audio` | read/write |
| `/home/homelabuser/RemoteDrop/Documents` | `/documents` | read-only |

The Audio mount supports the folder watcher's `incoming`, `processing`,
`ready`, `failed`, and `archive` workflow. The Documents mount is deliberately
read-only. Knowledge APIs must not delete source files from either mount.

These absolute host paths make the Compose file server-specific. Their
existence, ownership, permissions, and contents are server-local concerns and
are not established by the repository.

## Build and rebuild

README documents this initial command after preparing `.env`:

```bash
docker compose up -d --build
```

This command builds and starts/recreates the service, so it must only be run
after explicit user approval. Documentation work and code review do not imply
permission to build, rebuild, restart, or deploy.

No separate, repository-defined deployment automation is present.

## Revision selection for production

Development changes must be made in a feature branch or a `codex/*` branch,
not directly in `main`. Merge into `main` requires completed manual
verification and explicit user confirmation.

That development rule is not a ban on deploying `main`. A stable production
deployment should ultimately use a verified `main` or an explicitly selected
release or tag. Production should not remain on a long-lived `codex/*` feature
branch. Selecting an acceptable revision does not itself authorize a build,
restart, or deployment; each of those operations still requires separate,
explicit user confirmation.

## Manual deployment checks

README identifies the interactive API documentation at:

```text
http://homelab:3010/docs
```

README also provides `./scripts/smoke_test.sh` (or the globally installed
`homelab-ai-test`) as a smoke test. These checks may contact running services
and must not be executed by an agent without explicit permission.

## Rollback

TODO: define and verify a repository-specific rollback procedure, including
the image/version selection, treatment of SQLite schema changes, and criteria
for restoring persistent state.

Until that procedure exists, do not invent a rollback command or assume that
checking out an older Git revision is sufficient. Any rollback requires an
explicit plan and user approval.

## Backup and restore

The repository does not contain a verified backup or restore procedure.

TODO: define and test a coordinated backup process for at least:

- server-local `.env`, stored securely without committing or printing it;
- SQLite state under `./data`;
- the configured Qdrant collection;
- source files under the RemoteDrop mounts, according to their external
  ownership and retention policy.

TODO: define and test restore order, service-stop requirements, validation,
and consistency rules between SQLite Knowledge state and Qdrant vectors.

No backup or restore commands are prescribed here until they have been
implemented and verified for this deployment.

## Deployment safety

- Do not commit `.env`, credentials, SQLite databases, logs, or model files.
- Do not display secret values in terminal output, diffs, or documentation.
- Do not make development changes directly in `main`; use a feature branch or
  a `codex/*` branch and merge only after manual verification and explicit
  user confirmation.
- Prefer a verified `main` or an explicitly selected release or tag for stable
  production. Do not treat a long-lived `codex/*` feature branch as the stable
  production revision.
- Review `git status` and the current branch before development changes.
- Tests, container operations, commit, push, and deployment require the
  permissions recorded in `AGENTS.md` and explicit user confirmation.
