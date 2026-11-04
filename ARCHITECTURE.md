# Architecture

## Overview

SimCrew runs AI personas against a git repository to evaluate its developer experience. A run starts one agent container per persona. Each agent clones the repository, works through a journey of phases with sandboxed tools, and reports evidence-backed findings. The orchestrator collects the findings, deduplicates and spot-checks them, and scores the run GREEN, YELLOW, or RED.

```
┌──────────────────────────────────────────────────────┐
│                React SPA (served on :8000)            │
│  Dashboard · Personas · Journeys · Environments ·     │
│  New Run (personas, environment, model) · Run detail  │
└──────────────────────────┬───────────────────────────┘
                           │ /api/*
┌──────────────────────────┴───────────────────────────┐
│              Orchestrator (FastAPI, SU_ROLE=orchestrator)
│  /api/personas  /api/journeys  /api/environments      │
│  /api/runs      /api/models    /api/prompts           │
│                                                      │
│  runner.py · orchestrator.py · supervisor.py ·        │
│  triage*.py · prompt_generator.py                     │
└───────┬──────────────────────────────┬───────────────┘
        │ PostgreSQL                   │ one agent per persona
        ▼                              ▼ (Docker container or K8s Job)
  ┌───────────┐          ┌────────────────────────────────┐
  │ Postgres  │          │ Agent (SU_ROLE=agent, :8080)    │
  └───────────┘          │ image = persona's environment   │
                         │   (default: SimCrew base image) │
                         │ git clone → journey phases →    │
                         │ tools → report_finding          │
                         └───────────────┬────────────────┘
                                         │ LLM calls
                                         ▼
                         Model provider: any OpenAI-compatible
                         endpoint (NVIDIA NIM by default), or
                         Claude via Anthropic / Vertex AI
```

The same container image runs both roles; `SU_ROLE` picks one at start (`backend/entrypoint.sh`).

## Data model

| Entity | What it is | Key fields |
|--------|-----------|------------|
| **Persona** | A synthetic developer, defined by structured fields rather than a raw prompt | name, role_label, identity, perspective, constraints, system_prompt (generated), prompt_approved |
| **Journey** | An ordered list of phases a persona works through | name, description, phases |
| **JourneyPhase** | One step of a journey | order, name, instructions |
| **Environment** | The container image a persona's agent runs in | name, image, description, is_builtin |
| **Run** | One evaluation of a repository | name, repo_url, journey_id, model, config, status, score, score_rationale, error |
| **RunPersona** | One persona's part of a run | persona_id, environment_id (nullable = default image), status, current_phase, blocked_phase, phase_summaries |
| **Finding** | One issue a persona reported | severity (critical / needs_attention / nits), category, title, description, evidence, file_path, line_range, suggestion, phase |

Built-in personas and journeys (the DX pack and the smoke test) are seeded idempotently on startup from `backend/app/seed/`.

## Run lifecycle

1. **Create** (`POST /api/runs`): the repo URL is validated (`https://` or `git@host:path`, no shell characters). The run's model defaults to the server's configured one if none is given (see [Models](#models)). Each persona's environment is checked against the image allowlist.
2. **Start agents** (`orchestrator.py`): one container per persona, using the persona's environment image or the default agent image. Docker locally; on Kubernetes, a Job plus Service per persona with no service-account token mounted.
3. **Health check and dispatch**: the orchestrator waits for each agent's `/health`, then sends `POST /run` with the persona, its environment description, the journey phases, the repo URL, and the model.
4. **Agent loop** (`runner.py`, inside the agent): the agent clones the repository, then for each phase runs a tool-use loop (at most 50 model calls per phase) until the model calls `complete_phase`. Progress and findings stream back through `/progress`; the final payload goes to `/done`.
5. **Score** (`supervisor.py`, deterministic): RED if any persona was blocked, any finding is critical, or there are 3 or more needs_attention findings; YELLOW for 1 or 2 needs_attention; otherwise GREEN.
6. **Triage** (`triage.py`, after the run): findings are deduplicated, spot-checked, and summarized into insights (see [Triage](#triage)).

The orchestrator fails a run whose agents haven't all reported done within `SU_AGENT_RUN_TIMEOUT` (default 1800 s).

## Personas and prompts

1. The user fills in the structured fields; `POST /api/prompts/generate` previews the system prompt.
2. `prompt_generator.py` wraps the fields in a template with mandatory sections: report every issue with `report_finding`, evidence must be verbatim tool output, and use only what the repository tells you.
3. The user approves the prompt; runs use the approved prompt.
4. A persona's environment changes only the image its agent runs in. The environment's description is never added to the prompt, so the agent finds out what's installed by running into it.

## Agent tools (`tools.py`)

| Tool | What it does | Limits |
|------|-------------|--------|
| `read_file` | Read a file in the cloned repo | Workspace only; path traversal and outside symlinks blocked; 10K characters |
| `list_directory` | List a directory | Same path limits |
| `run_command` | Run a shell command | Must start with an allowlisted prefix (`make`, `git`, `npm`, `pip`, `python`, `curl`, `helm`, `oc get`, …); blocklisted patterns rejected; timeout; 5K characters of output |
| `http_request` | Call a service the persona started | localhost only |
| `report_finding` | Record a finding | Severity, category, title, description, and verbatim evidence required |
| `complete_phase` | Finish the phase | Takes a summary |

The tool allowlist is a security boundary; the container is a second one.

## Models

- The model is chosen **per run**. `RunCreate.model` is optional: when it's omitted, `default_model()` picks `NVIDIA_NIM_MODEL` if `NVIDIA_API_KEY` is set, otherwise `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`). The resolved model is stored on the run.
- `GET /api/models` returns the default and, for OpenAI-compatible providers, the provider's model list. The New Run page suggests those but accepts any model id.
- **Providers** (`runner._build_client`, first match wins): `NVIDIA_API_KEY` → the NIM client (`nvidia_nim.py`) for NVIDIA or any OpenAI-compatible endpoint at `NVIDIA_NIM_BASE_URL`; `MODELS_CORP_API_KEY` → the Models.Corp client (deprecated); `ANTHROPIC_VERTEX_PROJECT_ID` → Vertex AI; otherwise the Anthropic API.
- **Resilience** in the NIM client: rate limits (429) are waited out up to 40 times, honoring `Retry-After`; server errors and dropped connections are retried with backoff and then fall back to `NVIDIA_NIM_FALLBACK_MODEL` if one is set (none by default); other 4xx errors fail fast. The thinking flag (`NVIDIA_NIM_ENABLE_THINKING`, off by default) is sent on every request.

## Environments

- An environment is a container image built `FROM ghcr.io/mpk-droid/simcrew` that keeps its entrypoint, so it still runs the agent server (example: `examples/environment/Dockerfile`).
- Users register environments in the UI or `/api/environments`, then pick one per persona on New Run. A persona without one uses the default agent image.
- `SU_ALLOWED_ENV_IMAGE_PREFIXES` (Helm: `environments.allowedImagePrefixes`) limits which images may be used. It's checked when an environment is saved and again when a run is created. Empty allows any image.
- An environment that runs reference can't be deleted (409). If an agent's environment image never becomes healthy, the run fails with an error that names the persona and image.

## Triage

After a run completes, `triage.py` runs three steps:

1. **Deduplicate** (`triage_dedup.py`): a conservative merge of near-identical findings, then the run's model reviews candidate groups (same category, same file, or similar titles) and merges those that describe the same issue. Findings are listed with short ids (`f1`, `f2`, …) in that prompt.
2. **Spot-check** (`triage_verify.py`): in a fresh clone, cited files and paths are checked and cited commands are re-run. Each cluster is marked `verified`, `contradicted`, or `unverified`.
3. **Insights**: per-persona and per-journey summaries for the run detail page.

## Deployment

- **Local**: `docker compose up --build` builds the image, starts Postgres and the orchestrator, and the orchestrator starts agent containers through the host Docker socket on the `simcrew` network. Keys and settings come from `.env`. `docker-compose.vertex.yml` adds gcloud credentials for Vertex.
- **Cluster** (`chart/`): Helm deploys the orchestrator, an optional bundled Postgres, a Route, a ServiceAccount with a Role to create agent Jobs and Services, and a NetworkPolicy that limits agent pods to the orchestrator, DNS, and the public internet. Images come from `ghcr.io/mpk-droid/simcrew`, published by CI for amd64 and arm64.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, SQLAlchemy (async, asyncpg), Alembic, httpx, Anthropic SDK |
| Database | PostgreSQL |
| Frontend | React, TypeScript, Vite, React Router, TanStack Query |
| LLM | Any OpenAI-compatible endpoint (NVIDIA NIM by default), or Claude via Anthropic or Vertex AI |
| Agents | Docker containers (local) or Kubernetes Jobs (cluster) |
| CI | GitHub Actions: lint, tests, type check, `helm lint`, DCO; image publish to GHCR |
