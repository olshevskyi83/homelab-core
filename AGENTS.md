# Repository Working Agreement

This file defines the working rules for automated coding agents and future
maintenance sessions in this repository.

## Confirmed system boundaries

- Homelab Core is the single owner of the Knowledge API, the Qdrant
  integration, and retrieval-augmented generation (RAG).
- Audio Lab and Document Lab are ingestion clients. They do not own separate
  Knowledge databases.
- Open WebUI is the central chat client. It accesses Knowledge through the
  OpenAI-compatible `homelab-knowledge` model exposed by Homelab Core.
- Audio and document sources share the collection configured by
  `QDRANT_COLLECTION`. `source_type` and `project` are metadata fields and
  optional search filters, not database boundaries.
- Deleting a Knowledge document or its index must not delete the source file.
- The active application entrypoint is `app.main:app`, as declared by the
  Dockerfile. The repository-root `app.py` is legacy code and is not copied or
  started by the current Docker image.

See `docs/ARCHITECTURE.md` for the verified runtime and API structure.

## Development workflow

- Work directly in the server workspace through VS Code Remote SSH.
- Before making changes, read the relevant repository documentation, run
  `git status`, and identify the current branch.
- Codex must never make changes directly in `main`. Development work must use
  a feature branch or a `codex/*` branch. Stop and ask the user before editing
  if the current branch is `main`.
- Merge into `main` only after manual verification and explicit user
  confirmation.
- Preserve existing user changes and keep work limited to the requested
  scope.
- Do not run tests, linters, `compileall`, Docker Compose commands, container
  commands, or external HTTP requests without separate user permission.
- After changes, give the user exact commands for manual verification and
  wait for the user to return the results.
- Commit, push, build, rebuild, restart, and deployment require explicit user
  confirmation. Approval for one action does not imply approval for another.
- Do not change `.env`.
- Do not print secrets, tokens, credentials, or the contents of the
  server-local `.env` in command output or documentation.
- Do not use destructive Git commands, including `git reset --hard`, forced
  checkout, forced push, or commands that discard uncommitted work.

## Production workflow

- The development prohibition on changing `main` directly does not prohibit
  production deployment from `main`.
- A stable production deployment should ultimately use a verified `main` or
  an explicitly selected release or tag.
- Production should not remain deployed from a long-lived `codex/*` feature
  branch.
- Every build, rebuild, restart, and deployment still requires separate,
  explicit user confirmation, regardless of the selected revision.

## Sources of truth

- Runtime entrypoint: `Dockerfile` and `app/main.py`
- API routes: `app/main.py` and `app/api/`
- Tracked deployment topology: `docker-compose.yml`
- Documented environment keys and example values: `.env.example`
- Runtime settings: `app/config.py`
- Knowledge behavior: `app/services/knowledge_service.py`,
  `app/services/knowledge_state.py`, and `app/providers/qdrant.py`
- Deployment notes: `docs/DEPLOYMENT.md`

When documentation and implementation disagree, report the discrepancy. Do
not silently present an assumption as deployed fact.

## Repository safety

Never commit server-local configuration or runtime artifacts, including:

- `.env` and credentials;
- API tokens;
- SQLite databases and other files under `data/`;
- logs;
- model files.

Knowledge deletion is source-agnostic at the index and state layers. It must
not be extended to delete files owned by Audio Lab, Document Lab, or another
ingestion client.
