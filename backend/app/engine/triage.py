"""Orchestrator triage — dedupe, verify, and persona insights for completed runs."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.engine.runner import _build_client
from app.engine.tools import ToolContext
from app.engine.triage_dedup import FindingCluster, deduplicate_findings
from app.engine.triage_verify import (
    cleanup_workspace,
    evidence_quality_check,
    prepare_workspace,
    spot_check_cluster,
)
from app.engine.usage import MeteredClient
from app.models.run import Run, RunPersona

logger = logging.getLogger(__name__)

_active_triage_runs: set[str] = set()


def _persona_insight_suggestion(kind: str) -> str:
    if kind == "inaccurate_finding":
        return "Require verbatim tool output before reporting a finding."
    if kind == "blocked":
        return "Review journey instructions for phases where this persona gets blocked."
    if kind == "low_signal":
        return (
            "Make this persona's perspective more specific so they report "
            "concrete DX issues."
        )
    return "Review this persona's fields for clearer evaluation boundaries."


def _build_insights(
    run_personas: list[RunPersona],
    persona_names: dict[uuid.UUID, str],
    contradicted: list[tuple[FindingCluster, str]],
) -> list[dict]:
    insights: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for cluster, reason in contradicted:
        title = cluster.finding.get("title", "Untitled finding")
        for persona in cluster.personas:
            key = ("inaccurate_finding", persona, title)
            if key in seen:
                continue
            seen.add(key)
            insights.append(
                {
                    "scope": "persona",
                    "persona": persona,
                    "kind": "inaccurate_finding",
                    "message": (
                        f'Reported "{title}" but the orchestrator '
                        f"could not confirm it: {reason}"
                    ),
                    "suggestion": _persona_insight_suggestion("inaccurate_finding"),
                }
            )

    for rp in run_personas:
        name = persona_names.get(rp.persona_id, str(rp.persona_id))
        if rp.blocked_phase:
            key = ("blocked", name, rp.blocked_phase)
            if key not in seen:
                seen.add(key)
                reason = rp.blocked_reason or "No reason recorded."
                insights.append(
                    {
                        "scope": "persona",
                        "persona": name,
                        "kind": "blocked",
                        "message": (
                            f"Blocked at {rp.blocked_phase}: {reason}"
                        ),
                        "suggestion": _persona_insight_suggestion("blocked"),
                    }
                )

        if rp.status.value == "completed" and not rp.findings:
            summaries = " ".join((rp.phase_summaries or {}).values()).lower()
            if not summaries or len(summaries) < 40:
                key = ("low_signal", name, "no_findings")
                if key not in seen:
                    seen.add(key)
                    insights.append(
                        {
                            "scope": "persona",
                            "persona": name,
                            "kind": "low_signal",
                            "message": (
                                "Finished without reporting findings and left "
                                "little phase commentary — they may have wandered "
                                "off-scope."
                            ),
                            "suggestion": _persona_insight_suggestion("low_signal"),
                        }
                    )

    return insights


def _journey_insight_suggestion(kind: str) -> str:
    if kind == "blocked_cluster":
        return "Review journey instructions for that phase — multiple personas hit the same wall."
    if kind == "all_blocked":
        return (
            "Check repo accessibility, journey phase order, and whether instructions "
            "assume tools the repo does not provide."
        )
    if kind == "verification_gaps":
        return (
            "Tighten journey prompts to require command output or file quotes "
            "before reporting issues."
        )
    if kind == "consensus_findings":
        return "Prioritize triaged findings with multiple reporters when planning fixes."
    return "Review journey phase instructions and expected outcomes."


def _build_journey_insights(
    run_personas: list[RunPersona],
    persona_names: dict[uuid.UUID, str],
    triaged_findings: list[dict],
    contradicted: list[tuple[FindingCluster, str]],
) -> list[dict]:
    insights: list[dict] = []
    seen: set[tuple[str, str]] = set()

    blocked_by_phase: dict[str, list[str]] = {}
    for rp in run_personas:
        if not rp.blocked_phase:
            continue
        name = persona_names.get(rp.persona_id, str(rp.persona_id))
        blocked_by_phase.setdefault(rp.blocked_phase, []).append(name)

    for phase, personas in blocked_by_phase.items():
        if len(personas) < 2:
            continue
        key = ("blocked_cluster", phase)
        if key in seen:
            continue
        seen.add(key)
        persona_list = ", ".join(personas)
        insights.append(
            {
                "scope": "journey",
                "kind": "blocked_cluster",
                "message": (
                    f"{len(personas)} personas were blocked at {phase}: "
                    f"{persona_list}."
                ),
                "suggestion": _journey_insight_suggestion("blocked_cluster"),
            }
        )

    if run_personas and all(rp.blocked_phase for rp in run_personas):
        key = ("all_blocked", "all")
        if key not in seen:
            seen.add(key)
            insights.append(
                {
                    "scope": "journey",
                    "kind": "all_blocked",
                    "message": "Every persona was blocked before completing the journey.",
                    "suggestion": _journey_insight_suggestion("all_blocked"),
                }
            )

    if len(contradicted) >= 2:
        key = ("verification_gaps", "count")
        if key not in seen:
            seen.add(key)
            insights.append(
                {
                    "scope": "journey",
                    "kind": "verification_gaps",
                    "message": (
                        f"The orchestrator contradicted {len(contradicted)} reported "
                        "findings — personas may be inferring instead of citing evidence."
                    ),
                    "suggestion": _journey_insight_suggestion("verification_gaps"),
                }
            )

    multi_persona = [
        finding
        for finding in triaged_findings
        if len(finding.get("personas", [])) >= 2
    ]
    if len(multi_persona) >= 3:
        key = ("consensus_findings", "count")
        if key not in seen:
            seen.add(key)
            insights.append(
                {
                    "scope": "journey",
                    "kind": "consensus_findings",
                    "message": (
                        f"{len(multi_persona)} findings were reported independently "
                        "by multiple personas — likely real DX issues."
                    ),
                    "suggestion": _journey_insight_suggestion("consensus_findings"),
                }
            )

    return insights



def _cluster_to_triaged(
    cluster: FindingCluster,
    verification_status: str,
    verification_note: str,
) -> dict:
    finding = cluster.finding
    return {
        "id": str(uuid.uuid4()),
        "severity": finding["severity"],
        "category": finding["category"],
        "title": finding["title"],
        "description": finding["description"],
        "evidence": finding["evidence"],
        "file_path": finding.get("file_path"),
        "suggestion": finding.get("suggestion"),
        "phase": finding["phase"],
        "personas": cluster.personas,
        "source_finding_ids": cluster.source_ids,
        "verification_status": verification_status,
        "verification_note": verification_note,
    }


async def triage_run(run_id: str) -> None:
    """Run triage once per run at a time."""
    if run_id in _active_triage_runs:
        return
    _active_triage_runs.add(run_id)
    try:
        await _triage_run_body(run_id)
    finally:
        _active_triage_runs.discard(run_id)


async def _triage_run_body(run_id: str) -> None:
    """Deduplicate findings, verify evidence, and store orchestrator triage."""
    from app.db.session import async_session

    triaged_count = 0
    insight_count = 0
    client = None

    try:
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
                return

            existing = (run.metadata_ or {}).get("triage")
            if existing and existing.get("status") == "complete":
                return

            metadata = dict(run.metadata_ or {})
            metadata["triage"] = {
                "status": "pending",
                "triaged_findings": [],
                "insights": [],
            }
            run.metadata_ = metadata
            flag_modified(run, "metadata_")
            await db.commit()

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
                return

            persona_names = {
                rp.persona_id: rp.persona.name if rp.persona else str(rp.persona_id)
                for rp in run.run_personas
            }

            raw_findings: list[dict] = []
            for rp in run.run_personas:
                persona_name = persona_names.get(rp.persona_id, str(rp.persona_id))
                for finding in rp.findings:
                    raw_findings.append(
                        {
                            "id": str(finding.id),
                            "severity": finding.severity.value,
                            "category": finding.category,
                            "title": finding.title,
                            "description": finding.description,
                            "evidence": finding.evidence,
                            "file_path": finding.file_path,
                            "line_range": finding.line_range,
                            "suggestion": finding.suggestion,
                            "phase": finding.phase,
                            "_persona": persona_name,
                        }
                    )

            try:
                client = MeteredClient(_build_client(run.config or {}))
            except Exception:
                logger.warning("Triage LLM client unavailable", exc_info=True)

            clusters = await deduplicate_findings(
                raw_findings,
                client=client,
                model=run.model,
            )

            workspace = await prepare_workspace(run.repo_url)
            tool_ctx = None
            if workspace:
                config = run.config or {}
                tool_ctx = ToolContext(
                    workspace_dir=workspace,
                    command_timeout=config.get("command_timeout", 120),
                    build_timeout=config.get("build_timeout", 300),
                )

            triaged_findings: list[dict] = []
            contradicted: list[tuple[FindingCluster, str]] = []

            try:
                for cluster in clusters:
                    try:
                        status, note = await spot_check_cluster(
                            cluster.finding,
                            cluster.personas,
                            tool_ctx,
                        )
                    except Exception as exc:
                        logger.warning("Spot-check failed for run %s", run_id, exc_info=True)
                        status, note = "unverified", f"Spot-check failed: {exc}"
                    if status == "contradicted":
                        contradicted.append((cluster, note))
                        continue

                    if status == "unverified":
                        ok, quality_note = evidence_quality_check(cluster.finding)
                        if not ok:
                            note = quality_note

                    triaged_findings.append(_cluster_to_triaged(cluster, status, note))
            finally:
                cleanup_workspace(workspace)
                if client and hasattr(client, "close"):
                    await client.close()

            persona_insights = _build_insights(
                run.run_personas, persona_names, contradicted
            )
            journey_insights = _build_journey_insights(
                run.run_personas,
                persona_names,
                triaged_findings,
                contradicted,
            )
            insights = persona_insights + journey_insights
            triaged_count = len(triaged_findings)
            insight_count = len(insights)

            metadata = dict(run.metadata_ or {})
            metadata["triage"] = {
                "status": "complete",
                "triaged_findings": triaged_findings,
                "insights": insights,
                "usage": client.snapshot() if client else {},
            }
            run.metadata_ = metadata
            flag_modified(run, "metadata_")
            await db.commit()
    except Exception:
        logger.exception("Triage failed for run %s", run_id)
        async with async_session() as db:
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one_or_none()
            if run:
                metadata = dict(run.metadata_ or {})
                metadata["triage"] = {
                    "status": "complete",
                    "triaged_findings": [],
                    "insights": [],
                    "error": "Triage failed",
                    "usage": client.snapshot() if client else {},
                }
                run.metadata_ = metadata
                flag_modified(run, "metadata_")
                await db.commit()
        return

    logger.info(
        "Triage complete for run %s (%d triaged, %d insights)",
        run_id,
        triaged_count,
        insight_count,
    )
