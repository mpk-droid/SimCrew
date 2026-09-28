# SimCrew

AI synthetic developers that test the developer experience of your software. Give it a git repo URL — it spins up isolated agent containers (one per persona), each clones the repo and evaluates it like a real developer. Findings are deduplicated, scored GREEN/YELLOW/RED, and viewable in the built-in UI.

## How It Works

1. **Define personas** — each with an identity, perspective, and constraints (e.g., "backend developer who has never used AI" or "platform engineer evaluating for OpenShift deployment")
2. **Define a journey** — ordered phases like "Read the docs", "Set up locally", "Test the API", "Try deploying"
3. **Point at a repo** — provide a git repository URL
4. **Get a report** — each persona independently clones the repo, follows the journey phases, and reports findings with evidence. All tools (file reading, command execution, HTTP requests) are always available.

Findings are scored GREEN / YELLOW / RED and stored in a database. A built-in UI shows run history, findings, and reports.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- One of: `NVIDIA_API_KEY` (recommended), `ANTHROPIC_API_KEY`, or Vertex AI credentials (`ANTHROPIC_VERTEX_PROJECT_ID` + `CLOUD_ML_REGION`)

### Run with Docker Compose

```bash
git clone <repo-url> && cd SimCrew

# Set your LLM credentials
export NVIDIA_API_KEY=nvapi-...  # https://build.nvidia.com/settings
export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
export CLOUD_ML_REGION=us-east5
# Or: export ANTHROPIC_API_KEY=sk-...

# Start everything
docker compose up
```

The app is at **http://localhost:8000** — API, UI, and health check all on one port.

### Run Your First Evaluation

**Via the UI:**
1. Open http://localhost:8000
2. Built-in personas and journeys (DX evaluation + smoke test) are pre-loaded on startup
3. Click "New Run", enter a repository URL, select personas, and start

**Via the API:**

```bash
# List available personas
curl http://localhost:8000/api/personas

# List available journeys
curl http://localhost:8000/api/journeys

# Create a run (replace IDs from the responses above)
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Evaluate my-service",
    "repo_url": "https://github.com/org/my-service.git",
    "persona_environments": [{"persona_id": "<persona-uuid>", "environment_id": null}],
    "journey_id": "<journey-uuid>",
    "model": "nvidia/nemotron-3-ultra-550b-a55b"
  }'

# Check run detail
curl http://localhost:8000/api/runs/<run-id>

# Delete a run
curl -X DELETE http://localhost:8000/api/runs/<run-id>
```

## Architecture

Each persona runs in its own Docker container. The orchestrator manages the lifecycle:

```
repo_url ──▶ Orchestrator (FastAPI + Postgres)
                    │
         ┌──────────┼──────────┐
         │          │          │
    Agent: Priya  Agent: Sam  Agent: Dana  ...
    (container)   (container) (container)
         │          │          │
    git clone    git clone   git clone
    read docs    follow setup read source
    run commands try to run  test edges
         │          │          │
         └────▶ Findings ◀────┘
                    │
            Deduplicate & Score
            (GREEN / YELLOW / RED)
```

The same Docker image serves both roles via `SU_ROLE` environment variable:
- `orchestrator` (default) — runs the FastAPI app with UI, DB, and container management
- `agent` — runs a lightweight server that clones repos and executes the LLM tool-use loop

## Cursor

This repo is set up for [Cursor](https://cursor.com) (not Claude Code CLI):

| File | Purpose |
|------|---------|
| `AGENTS.md` | Project context for any coding agent |
| `.cursor/rules/` | Scoped rules (always-on project context, backend Python, frontend React) |
| `.vscode/tasks.json` | Run tasks via **Cmd+Shift+P → Tasks: Run Task** |

**Quick start in Cursor:** Run task `docker: up` (full stack on http://localhost:8000) or `dev: full stack` (Postgres + hot-reload backend and frontend).

`.claude/` is ignored by git — use it only if you also use Claude Code CLI.

## Local Development

For hot-reload during development, run the backend and frontend separately:

```bash
# Start Postgres
docker compose up db -d

# Backend (FastAPI with hot reload)
cd backend
uv sync
DATABASE_URL="postgresql+asyncpg://synthetic:synthetic@localhost:5432/synthetic_users" \
  uv run uvicorn app.main:app --port 8000 --reload

# Frontend (Vite dev server with API proxy)
cd frontend
npm install
npm run dev    # opens on :5174, proxies /api/* to :8000 (:5173 is Gmail Buddy)
```

## Creating Custom Personas

Personas are defined by structured fields, not raw prompts. The service generates the system prompt for you.

**Via the UI:**
1. Go to Personas → Create Persona
2. Fill in: Name, Identity, Perspective, Constraints, Expertise Level
3. Click "Preview Prompt" to see the generated system prompt
4. Adjust fields if needed, then create
5. Review the system prompt and click "Approve"

**Via the API:**

```bash
# Preview a prompt without saving
curl -X POST http://localhost:8000/api/prompts/generate \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Principal Engineer",
    "identity": "Staff engineer with 15 years experience evaluating SDKs",
    "perspective": "API ergonomics, error handling, integration complexity",
    "constraints": "Knows distributed systems but has not used this product before"
  }'

# Create the persona
curl -X POST http://localhost:8000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Principal Engineer",
    "identity": "Staff engineer with 15 years experience evaluating SDKs",
    "perspective": "API ergonomics, error handling, integration complexity",
    "constraints": "Knows distributed systems but has not used this product before",
    "role_label": "Staff engineer"
  }'

# Approve the generated prompt
curl -X POST http://localhost:8000/api/personas/<id>/approve-prompt
```

## Built-in DX Evaluation

Ships with 4 personas designed for evaluating developer tools and templates:

| Persona | Role | Catches |
|---------|------|---------|
| **Priya** | Engineering Director | Unclear value props, jargon-heavy docs, missing business context |
| **Sam** | AI Novice (backend dev) | Unexplained AI terminology, missing setup guidance, assumed knowledge |
| **Dana** | Production Engineer | Poor error handling, tight coupling, production anti-patterns |
| **Kai** | Platform Engineer | Missing resource limits, deployment issues, operational gaps |

And a 5-phase journey: First Impressions → Setup → Running Locally → Using the Target → Deployment.


## Custom Environments

> **Work in progress** — environment CRUD and per-persona assignment are disabled in the UI and API. Runs use the default agent image. The notes below describe the planned workflow.

Agents run inside container images. **Default** uses the built-in SimCrew agent image. To simulate a different OS or toolchain, publish a variant of the base image and register it as an Environment.

**Base image (published on Quay):**

```
quay.io/rh-ee-mpk/synthetic-users:latest
```

This image includes the SimCrew agent server (`SU_ROLE=agent`). Custom environment images must extend it — do not use an unrelated container image.

### 1. Build your variant

```bash
# Start from the example
cp examples/environment/Dockerfile ./Dockerfile.env
# Edit: add packages, change OS tooling, etc.
docker build -f Dockerfile.env -t quay.io/rh-ee-mpk/synthetic-users-fedora:latest .
docker push quay.io/rh-ee-mpk/synthetic-users-fedora:latest
```

Minimal `Dockerfile`:

```dockerfile
FROM quay.io/rh-ee-mpk/synthetic-users:latest

USER 0
RUN dnf install -y --nodocs <your-packages> && dnf clean all
USER 1001
```

### 2. Register in the UI

1. Open **Environments** → **Add Environment**
2. **Name** — e.g. `Fedora + Go`
3. **Docker Image** — your pushed image (e.g. `quay.io/rh-ee-mpk/synthetic-users-fedora:latest`)
4. **Description** — optional; shown in the persona prompt (e.g. `Fedora 40 with Go installed`)

### 3. Use on a run

On **New Run**, select personas and pick an environment per persona. Leave **Default** to use the base agent image.

### Registry access

The cluster or Docker host running agents must be able to **pull** the image. Public Quay repos work out of the box. Private repos need registry credentials (`docker login quay.io` locally, or an OpenShift `imagePullSecret`).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (orchestrator) | PostgreSQL connection string (asyncpg) |
| `ANTHROPIC_VERTEX_PROJECT_ID` | One of these | Vertex AI project ID |
| `CLOUD_ML_REGION` | | Vertex AI region |
| `ANTHROPIC_API_KEY` | | Direct Anthropic API key (if not using Vertex) |
| `SU_ROLE` | No | `orchestrator` (default) or `agent` |
| `SU_AGENT_IMAGE` | No | Docker image for agent containers |
| `SU_DOCKER_NETWORK` | No | Docker network for agent containers |

## Deploying to OpenShift / Kubernetes

### Build and Push the Image

```bash
docker build -t quay.io/rh-ee-mpk/synthetic-users:latest .
docker push quay.io/rh-ee-mpk/synthetic-users:latest
```

### Deploy with Helm

```bash
helm install simcrew ./chart \
  --set image.repository=quay.io/rh-ee-mpk/synthetic-users \
  --set image.tag=latest \
  --set secrets.vertexProjectId=your-gcp-project \
  --set secrets.vertexRegion=us-east5 \
  --set postgresql.auth.password=your-db-password
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/personas` | GET, POST | List / create personas |
| `/api/personas/{id}` | GET, PUT, DELETE | Get / update / delete persona |
| `/api/personas/{id}/generate-prompt` | POST | Regenerate system prompt from fields |
| `/api/personas/{id}/approve-prompt` | POST | Mark prompt as approved |
| `/api/journeys` | GET, POST | List / create journeys |
| `/api/journeys/{id}` | GET, PUT, DELETE | Get / update / delete journey |
| `/api/journeys/{id}/phases` | POST | Add phase to journey |
| `/api/journeys/{id}/phases/{pid}` | PUT, DELETE | Update / delete phase |
| `/api/runs` | GET, POST | List / create runs |
| `/api/runs/{id}` | GET, DELETE | Run detail / delete run |
| `/api/runs/{id}/findings` | GET | All findings for a run |
| `/api/prompts/generate` | POST | Preview prompt from structured fields |

Full OpenAPI docs at http://localhost:8000/docs.
