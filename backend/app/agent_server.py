"""Lightweight agent server — runs inside each agent container.

Receives a run request, clones the repo, executes all phases, and
reports progress via orchestrator endpoints:
  - POST /status after each phase starts
  - POST /done when finished (with all findings)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from app.engine.runner import execute_agent_run

logger = logging.getLogger(__name__)

app = FastAPI(title="SimCrew Agent")


class AgentRunRequest(BaseModel):
    persona: dict
    phases: list[dict]
    repo_url: str
    orchestrator_url: str
    model: str = "claude-sonnet-4-6"
    config: dict = Field(default_factory=dict)
    git_credentials: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", status_code=202)
async def run_agent(request: AgentRunRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_agent_background, request)
    return {"status": "accepted"}


async def _run_agent_background(request: AgentRunRequest) -> None:
    workspace = Path(tempfile.mkdtemp(prefix="su-workspace-"))
    clone_path = workspace / "repo"
    persona_id = request.persona.get("persona_id") or request.persona.get("id", "unknown")
    orchestrator_url = request.orchestrator_url

    async def on_phase_started(phase_name: str) -> None:
        await _post(
            f"{orchestrator_url}/status",
            {"persona_id": persona_id, "current_phase": phase_name},
        )

    async def on_event(event_type: str, data: dict) -> None:
        if event_type == "phase_started":
            await on_phase_started(data["phase"])
        elif event_type == "phase_completed":
            await _post(
                f"{orchestrator_url}/progress",
                {
                    "persona_id": persona_id,
                    "event_type": "phase_completed",
                    "message": f"Completed phase: {data['phase']}",
                    "data": {
                        "phase": data["phase"],
                        "summary": data.get("phase_summary", ""),
                    },
                },
            )
        elif event_type == "finding":
            finding = data["finding"]
            await _post(
                f"{orchestrator_url}/progress",
                {
                    "persona_id": persona_id,
                    "event_type": "finding",
                    "message": f"Finding: {finding.get('title', 'untitled')}",
                    "data": {"finding": finding},
                },
            )
        elif event_type == "tool":
            await _post(
                f"{orchestrator_url}/progress",
                {
                    "persona_id": persona_id,
                    "event_type": "tool",
                    "message": data.get("message", ""),
                    "data": {},
                },
            )

    try:
        await clone_repo(request.repo_url, str(clone_path), request.git_credentials)

        result = await execute_agent_run(
            persona=request.persona,
            phases=request.phases,
            model=request.model,
            config=request.config,
            workspace_dir=str(clone_path),
            on_event=on_event,
        )

        await _post(
            f"{orchestrator_url}/done",
            {
                "persona_id": persona_id,
                "status": result["status"],
                "phase_summaries": result["phase_summaries"],
                "findings": result["findings"],
                "blocked_phase": result.get("blocked_phase"),
                "blocked_reason": result.get("blocked_reason"),
            },
        )

    except Exception as e:
        logger.exception("Agent run failed")
        await _post(
            f"{orchestrator_url}/done",
            {
                "persona_id": persona_id,
                "status": "blocked",
                "phase_summaries": {},
                "findings": [],
                "blocked_phase": "startup",
                "blocked_reason": str(e),
            },
        )


async def _post(url: str, payload: dict) -> None:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return
        except Exception:
            logger.warning(
                "POST attempt %d failed for %s", attempt + 1, url, exc_info=True
            )
            if attempt < 2:
                await asyncio.sleep(2**attempt)
    logger.error("All POST attempts failed for %s", url)


async def clone_repo(
    repo_url: str, clone_path: str, credentials: str | None = None
) -> None:
    env = None
    if credentials:
        env = {"GIT_ASKPASS": "echo", "GIT_PASSWORD": credentials}

    cmd = f"git clone --depth 1 {repo_url} {clone_path}"
    logger.info("Cloning %s into %s", repo_url, clone_path)

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = stdout.decode(errors="replace")

    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed (exit {proc.returncode}): {output}")

    logger.info("Clone complete: %s", clone_path)
