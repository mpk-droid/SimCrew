"""Run engine — executes persona agents through journey phases."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import anthropic

from app.engine.supervisor import score_run
from app.engine.tools import ToolContext, execute_tool, get_all_tools
from app.engine.usage import MeteredClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 50


def _build_client(config: dict):
    nvidia_api_key = config.get("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY")
    if nvidia_api_key:
        from app.engine.nvidia_nim import (
            DEFAULT_BASE_URL,
            DEFAULT_MODEL,
            FALLBACK_MODEL,
            NvidiaNimClient,
        )

        base_url = config.get("nvidia_nim_base_url") or os.environ.get(
            "NVIDIA_NIM_BASE_URL", DEFAULT_BASE_URL
        )
        default_model = config.get("nvidia_nim_model") or os.environ.get(
            "NVIDIA_NIM_MODEL", DEFAULT_MODEL
        )
        fallback_model = config.get("nvidia_nim_fallback_model")
        if fallback_model is None:
            fallback_model = os.environ.get("NVIDIA_NIM_FALLBACK_MODEL", FALLBACK_MODEL)
        enable_thinking = config.get("nvidia_nim_enable_thinking")
        if enable_thinking is None:
            enable_thinking = os.environ.get(
                "NVIDIA_NIM_ENABLE_THINKING", "false"
            ).lower() in ("1", "true", "yes")
        logger.info(
            "Using NVIDIA NIM (%s, model=%s, fallback=%s)",
            base_url,
            default_model,
            fallback_model,
        )
        return NvidiaNimClient(
            api_key=nvidia_api_key,
            base_url=base_url,
            default_model=default_model,
            fallback_model=fallback_model,
            enable_thinking=enable_thinking,
        )

    models_corp_key = config.get("models_corp_api_key") or os.environ.get(
        "MODELS_CORP_API_KEY"
    )
    models_corp_url = config.get("models_corp_url") or os.environ.get(
        "MODELS_CORP_URL",
        "https://claude--apicast-production.apps.int.stc.ai.prod.us-east-1.aws.paas.redhat.com",
    )

    if models_corp_key:
        from app.engine.models_corp import ModelsCorpClient

        logger.info("Using Models.corp (%s)", models_corp_url)
        return ModelsCorpClient(
            base_url=models_corp_url,
            api_key=models_corp_key,
            verify_ssl=False,
        )

    vertex_project = config.get("vertex_project_id") or os.environ.get(
        "ANTHROPIC_VERTEX_PROJECT_ID"
    )
    vertex_region = config.get("vertex_region") or os.environ.get(
        "CLOUD_ML_REGION", os.environ.get("ANTHROPIC_VERTEX_REGION")
    )

    if vertex_project:
        logger.info(
            "Using Vertex AI (project=%s, region=%s)",
            vertex_project,
            vertex_region,
        )
        return anthropic.AsyncAnthropicVertex(
            project_id=vertex_project,
            region=vertex_region or "us-east5",
        )
    return anthropic.AsyncAnthropic()


async def run_persona_phase(
    client: anthropic.AsyncAnthropic | anthropic.AsyncAnthropicVertex,
    system_prompt: str,
    phase_instructions: str,
    phase_name: str,
    persona_name: str,
    tool_ctx: ToolContext,
    model: str,
    max_tokens: int = 4096,
    on_event=None,
) -> str:
    """Run a single persona through one journey phase."""
    tool_schemas = get_all_tools()
    messages: list[dict] = [{"role": "user", "content": phase_instructions}]

    logger.info("%s starting phase: %s", persona_name, phase_name)

    summary = ""
    for _ in range(MAX_ITERATIONS):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tool_schemas,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text_parts = [
                block.text for block in assistant_content if hasattr(block, "text")
            ]
            summary = "\n".join(text_parts) if text_parts else "Phase complete."
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            phase_complete = False
            for block in assistant_content:
                if block.type == "tool_use":
                    result_text, is_complete = await execute_tool(
                        block.name,
                        block.input,
                        tool_ctx,
                        phase_name,
                        persona_name,
                    )
                    if on_event:
                        detail = result_text[:120].replace("\n", " ")
                        if len(result_text) > 120:
                            detail += "..."
                        await on_event(
                            "tool",
                            {
                                "message": (
                                    f"Used {block.name}"
                                    + (f" — {detail}" if detail else "")
                                ),
                            },
                        )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        }
                    )
                    if is_complete:
                        summary = result_text
                        phase_complete = True

            messages.append({"role": "user", "content": tool_results})
            if phase_complete:
                break

    logger.info("%s completed phase: %s", persona_name, phase_name)
    return summary


async def execute_agent_run(
    persona: dict,
    phases: list[dict],
    model: str,
    config: dict,
    workspace_dir: str,
    on_event=None,
) -> dict:
    """Execute a single persona through all phases.

    This is what runs inside each agent container. The persona clones the
    repo into workspace_dir before this is called, then runs through all
    journey phases sequentially.

    Args:
        persona: Dict with id, name, system_prompt.
        phases: List of dicts with name, instructions, order.
        model: Anthropic model ID.
        config: Run config dict (timeouts, vertex settings, etc.).
        workspace_dir: Path to the cloned repository.
        on_event: Optional async callback(event_type, data) for progress.

    Returns:
        Dict with persona_id, phase_summaries, findings, blocked info.
    """
    client = MeteredClient(_build_client(config))
    max_tokens = config.get("max_tokens", 4096)
    command_timeout = config.get("command_timeout", 120)
    build_timeout = config.get("build_timeout", 300)

    persona_name = persona["name"]
    system_prompt = persona["system_prompt"]
    persona_id = persona["id"]

    tool_ctx = ToolContext(
        workspace_dir=workspace_dir,
        command_timeout=command_timeout,
        build_timeout=build_timeout,
    )

    phase_summaries: dict[str, str] = {}
    phase_usage: dict[str, dict] = {}
    blocked = False
    blocked_phase = None
    blocked_reason = None

    sorted_phases = sorted(phases, key=lambda p: p["order"])

    for phase in sorted_phases:
        phase_name = phase["name"]

        if on_event:
            await on_event("phase_started", {"phase": phase_name})

        before = client.snapshot()
        try:
            summary = await run_persona_phase(
                client=client,
                system_prompt=system_prompt,
                phase_instructions=phase["instructions"],
                phase_name=phase_name,
                persona_name=persona_name,
                tool_ctx=tool_ctx,
                model=model,
                max_tokens=max_tokens,
                on_event=on_event,
            )
            phase_summaries[phase_name] = summary

            if on_event:
                await on_event(
                    "phase_completed",
                    {"phase": phase_name, "phase_summary": summary},
                )

                new_findings = [
                    f for f in tool_ctx.findings if f.get("phase") == phase_name
                ]
                for finding in new_findings:
                    await on_event("finding", {"finding": finding})

        except Exception as e:
            logger.exception("%s blocked at phase %s", persona_name, phase_name)
            phase_summaries[phase_name] = f"BLOCKED: {e}"
            blocked = True
            blocked_phase = phase_name
            blocked_reason = str(e)
            break
        finally:
            after = client.snapshot()
            phase_usage[phase_name] = {
                key: after[key] - before[key]
                for key in ("calls", "input_tokens", "output_tokens")
            }

    for f in tool_ctx.findings:
        f["_persona"] = persona_name

    return {
        "persona_id": persona_id,
        "status": "blocked" if blocked else "completed",
        "phase_summaries": phase_summaries,
        "findings": tool_ctx.findings,
        "blocked_phase": blocked_phase,
        "blocked_reason": blocked_reason,
        "usage": {**client.snapshot(), "phases": phase_usage},
    }


async def finalize_run_if_complete(run_id: str) -> bool:
    """Score and mark run completed when all personas are terminal. Idempotent."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.session import async_session
    from app.models.run import (
        Run,
        RunPersonaStatus,
        RunStatus,
        TrafficLight,
    )

    async with async_session() as db:
        result = await db.execute(
            select(Run)
            .options(
                selectinload(Run.run_personas),
            )
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run or run.status != RunStatus.running:
            return False

        terminal = {RunPersonaStatus.completed, RunPersonaStatus.blocked}
        if not run.run_personas or not all(
            rp.status in terminal for rp in run.run_personas
        ):
            return False

    all_findings = await _load_findings_from_db(run_id)
    any_blocked = await _check_any_blocked(run_id)
    score, rationale, _action_items, _agreement = score_run(all_findings, any_blocked)

    async with async_session() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        run = result.scalar_one_or_none()
        if not run or run.status != RunStatus.running:
            return False

        run.completed_at = datetime.now(timezone.utc)
        run.score = TrafficLight(score)
        run.score_rationale = rationale
        if any_blocked:
            run.status = RunStatus.failed
            run.error = rationale
        else:
            run.status = RunStatus.completed
            run.error = None
        await db.commit()

    import asyncio

    from app.engine.triage import triage_run

    asyncio.create_task(triage_run(run_id))

    logger.info("Run %s finalized with score %s", run_id, score)
    return True


async def execute_orchestrated_run(
    run_id: str,
    personas: list[dict],
    phases: list[dict],
    model: str,
    config: dict,
    repo_url: str,
    run_persona_map: dict[str, str],
):
    """Execute a full run using the container orchestrator.

    Spins up one agent container per persona, waits for all to finish
    (agents POST results to orchestrator endpoints), then scores.
    """
    from app.engine.orchestrator import RunCancelledError, create_orchestrator

    orchestrator = create_orchestrator(config=config)

    try:
        await orchestrator.run_all(
            personas=personas,
            phases=phases,
            model=model,
            repo_url=repo_url,
            run_persona_map=run_persona_map,
            run_id=run_id,
        )
    except RunCancelledError:
        logger.info("Run %s orchestration cancelled", run_id)
        return

    await finalize_run_if_complete(run_id)


async def _load_findings_from_db(run_id: str) -> list[dict]:
    """Load all findings for a run from the database."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.session import async_session
    from app.models.run import Run, RunPersona

    async with async_session() as db:
        result = await db.execute(
            select(Run)
            .options(
                selectinload(Run.run_personas).selectinload(RunPersona.findings),
                selectinload(Run.run_personas).selectinload(RunPersona.persona),
            )
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return []

        findings = []
        for rp in run.run_personas:
            persona_name = rp.persona.name if rp.persona else str(rp.persona_id)
            for f in rp.findings:
                findings.append(
                    {
                        "id": str(f.id),
                        "severity": f.severity.value,
                        "category": f.category,
                        "title": f.title,
                        "description": f.description,
                        "evidence": f.evidence,
                        "file_path": f.file_path,
                        "line_range": f.line_range,
                        "suggestion": f.suggestion,
                        "phase": f.phase,
                        "_persona": persona_name,
                    }
                )
        return findings


async def _check_any_blocked(run_id: str) -> bool:
    """Check if any persona in this run was blocked."""
    from sqlalchemy import select

    from app.db.session import async_session
    from app.models.run import Run, RunPersona

    async with async_session() as db:
        result = await db.execute(
            select(RunPersona)
            .join(Run)
            .where(Run.id == run_id, RunPersona.blocked_phase.is_not(None))
        )
        return result.first() is not None
