# SimCrew

Microservice that runs AI synthetic users against any software target to evaluate developer experience. Users provide a git repository URL, the service spins up one container per persona, each clones the repo and independently evaluates it like a real developer, and findings are deduplicated, scored, and viewable in the built-in UI.

## Structure

```
SimCrew/
├── backend/                     # FastAPI + SQLAlchemy + Alembic
│   ├── app/
│   │   ├── main.py              # Orchestrator app entry, lifespan, static file serving
│   │   ├── agent_server.py      # Agent container app (receives run requests, clones repos)
│   │   ├── api/                 # Route handlers (personas, journeys, runs, prompts)
│   │   ├── models/              # SQLAlchemy models (persona, journey, run, finding)
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── engine/              # LLM agent loop, tools, orchestrator, supervisor, prompt generator
│   │   ├── db/                  # Async session factory + startup migrations
│   │   └── seed/                # Built-in personas and journeys (DX + smoke test)
│   ├── entrypoint.sh            # SU_ROLE dispatch (orchestrator vs agent)
│   ├── alembic/                 # DB migrations
│   └── pyproject.toml
├── frontend/                    # React + TypeScript + Vite
│   └── src/
│       ├── api/client.ts        # All API calls
│       ├── pages/               # Dashboard, Personas, Journeys, NewRun, RunDetail, etc.
│       └── components/          # Layout, ScoreBadge, SeverityBadge, StatusBadge
├── chart/                       # Helm chart for OpenShift/K8s
├── Dockerfile                   # Multi-stage: builds frontend + bundles into backend + dev tools
└── docker-compose.yml           # Local dev: orchestrator + postgres (agents spawned dynamically)
```

## Commands

```bash
# Full stack (one command — best for demos)
docker compose up --build

# Dev mode (hot reload)
docker compose up db -d
cd backend && DATABASE_URL="postgresql+asyncpg://synthetic:synthetic@localhost:5432/synthetic_users" \
  uv run uvicorn app.main:app --port 8000 --reload
cd frontend && npm run dev       # Vite on :5174 (see Local ports below)

# Frontend build
cd frontend && npm run build     # Output in frontend/dist/

# Lint
cd backend && uv run ruff check app/ && uv run ruff format --check app/
cd frontend && npx tsc --noEmit
```

In Cursor, use **Terminal → Run Task** (`Cmd+Shift+P` → "Tasks: Run Task") for `docker: up` or `dev: full stack`.

## Local ports (Gmail Buddy conflict)

**Gmail Buddy** on this machine uses **:5173** (frontend) and **:3001** (backend). Do **not** use those for SimCrew.

| Service | Port |
|---------|------|
| SimCrew (docker full stack) | **8000** (UI + API) |
| SimCrew backend (dev) | **8000** |
| SimCrew frontend (dev) | **5174** → proxies `/api` to :8000 |

Open dev UI at http://localhost:5174 — not :5173.

## Code Style

- Python 3.12+, ruff (line-length 88, double quotes, select E/F/I)
- `from __future__ import annotations` in all Python files
- Async everywhere (SQLAlchemy async, FastAPI async handlers)
- TypeScript strict mode for frontend
- No CSS framework — plain CSS with custom properties in App.css

## Architecture

- **Personas** are defined by structured fields (identity, perspective, constraints, role_label). The service generates a system prompt from these fields. Users review and approve the prompt before it's used in runs.
- **Journeys** are ordered sequences of phases. Each phase has instructions that the persona follows independently.
- **Runs** evaluate a target repo. A run specifies a `repo_url`, selected personas, and a journey. The orchestrator spins up one Docker container per persona, each clones the repo and runs through all journey phases.
- **Engine** has two modes:
  - **Orchestrator** (`app/main.py`): receives runs, manages agent container lifecycle via Docker SDK, collects findings, deduplicates, scores (GREEN/YELLOW/RED).
  - **Agent** (`app/agent_server.py`): clones the repo, runs the LLM tool-use loop (Claude via Anthropic SDK), reports findings back to the orchestrator.

## Key Files

- `backend/app/engine/runner.py` — `execute_agent_run` (single persona) + `execute_orchestrated_run` (container fan-out)
- `backend/app/engine/orchestrator.py` — Docker container lifecycle (start, health check, collect results, cleanup)
- `backend/app/engine/tools.py` — tool implementations + allowlist/blocklist (all tools always available)
- `backend/app/engine/supervisor.py` — deterministic deduplication + scoring logic
- `backend/app/engine/prompt_generator.py` — structured fields → system prompt
- `backend/app/agent_server.py` — agent container FastAPI app (POST /run, GET /health)
- `backend/app/seed/dx_pack.py` — built-in DX personas and journey
- `backend/app/seed/test_pack.py` — built-in smoke-test personas and journey
- `backend/app/api/runs.py` — run creation + background orchestrated execution
- `backend/entrypoint.sh` — SU_ROLE-based dispatch (orchestrator vs agent)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (orchestrator) | PostgreSQL connection string (asyncpg) |
| `ANTHROPIC_VERTEX_PROJECT_ID` | One of these | Vertex AI project ID |
| `CLOUD_ML_REGION` | | Vertex AI region |
| `ANTHROPIC_API_KEY` | | Direct Anthropic API key (if not using Vertex) |
| `NVIDIA_API_KEY` | One of these | NVIDIA NIM API key ([build.nvidia.com](https://build.nvidia.com/settings)) |
| `NVIDIA_NIM_BASE_URL` | No | Default `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_NIM_MODEL` | No | Default `nvidia/nemotron-3-ultra-550b-a55b` |
| `NVIDIA_NIM_FALLBACK_MODEL` | No | Default `nvidia/nemotron-3-super-120b-a12b` (after primary 5xx retries) |
| `NVIDIA_NIM_ENABLE_THINKING` | No | Default `false` (reasoning mode can 500 on Ultra) |
| `SU_ROLE` | No | `orchestrator` (default) or `agent` |
| `SU_AGENT_IMAGE` | No | Docker image for agent containers (default: `synthetic-users:latest`) |
| `SU_DOCKER_NETWORK` | No | Docker network for agent containers |

Copy `.env.example` to `.env` for local shell exports. Docker Compose reads `ANTHROPIC_API_KEY` and `ANTHROPIC_VERTEX_PROJECT_ID` from your environment.

## Test runs (agents: always use these)

When validating workflows, UI, cluster deploys, or LLM integration — **do not** use the full DX evaluation unless explicitly testing that path.

| Use | Value |
|-----|-------|
| **Journey** | **Smoke Test Journey** (4 phases) |
| **Personas** | **Alex (Test)**, **Blake (Test)**, **Casey (Test)** — use all three |
| **Repo** | `https://github.com/mpk-droid/synthetic-users-smoke-test.git` |

Seeded from `backend/app/seed/test_pack.py` on orchestrator startup.



## Custom agent environments

**Work in progress** — do not enable environment CRUD or per-persona assignment in product flows until this ships. `POST`/`PUT`/`DELETE` `/api/environments` return `503`; runs reject non-null `environment_id`.

Published base image: `quay.io/rh-ee-mpk/synthetic-users:latest`

Custom environments must `FROM` this image (see `examples/environment/Dockerfile`). Users register variants in **Environments**, then assign per persona on **New Run**. The orchestrator pulls `environment.image` when starting each agent container.

## Boundaries

- Don't modify the engine's evidence verification logic without understanding the security implications
- Tool allowlists/blocklists in `engine/tools.py` are a security boundary — the container provides additional sandboxing
- The prompt generator template in `engine/prompt_generator.py` includes mandatory instructions (evidence requirements, tool usage) — don't remove those sections
- The seed data in `seed/dx_pack.py` is idempotent — it checks before inserting

## Cursor / Agent Workflow

- Run commands yourself (docker, curl, uv, npm) — do not ask the user to run them unless blocked.
- For demos: `docker compose up --build` then open http://localhost:8000
- Scoped rules in `.cursor/rules/` cover backend Python and frontend React conventions.
- `.claude/` is for Claude Code only; Cursor uses `AGENTS.md` and `.cursor/rules/`.
