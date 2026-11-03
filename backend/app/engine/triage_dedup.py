"""Finding deduplication for orchestrator triage."""

from __future__ import annotations

import difflib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

OBVIOUS_DUPE_THRESHOLD = 0.85
CANDIDATE_DUPE_THRESHOLD = 0.5

_SEVERITY_ORDER = {"critical": 3, "needs_attention": 2, "nits": 1}


@dataclass
class FindingCluster:
    finding: dict
    personas: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


def _norm_path(path: str | None) -> str:
    if not path:
        return ""
    return path.strip().lstrip("./")


def _title_ratio(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _pick_canonical(findings: list[dict]) -> dict:
    return max(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(f.get("severity", ""), 0),
            len((f.get("evidence") or "")),
            len((f.get("description") or "")),
        ),
    )


def _merge_findings(findings: list[dict]) -> FindingCluster:
    canonical = _pick_canonical(findings)
    personas: list[str] = []
    source_ids: list[str] = []
    for finding in findings:
        persona = finding.get("_persona", "")
        if persona and persona not in personas:
            personas.append(persona)
        finding_id = finding.get("id")
        if finding_id and finding_id not in source_ids:
            source_ids.append(finding_id)
    return FindingCluster(
        finding=dict(canonical),
        personas=personas,
        source_ids=source_ids,
    )


def conservative_merge(findings: list[dict]) -> list[FindingCluster]:
    """Merge only very obvious duplicates within category + file buckets."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for finding in findings:
        key = (finding.get("category", ""), _norm_path(finding.get("file_path")))
        buckets[key].append(finding)

    clusters: list[FindingCluster] = []
    for bucket in buckets.values():
        if len(bucket) == 1:
            clusters.append(_merge_findings(bucket))
            continue

        parent = list(range(len(bucket)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for i, left in enumerate(bucket):
            for j in range(i + 1, len(bucket)):
                if _title_ratio(left["title"], bucket[j]["title"]) >= OBVIOUS_DUPE_THRESHOLD:
                    union(i, j)

        groups: dict[int, list[dict]] = defaultdict(list)
        for index, finding in enumerate(bucket):
            groups[find(index)].append(finding)

        for group in groups.values():
            clusters.append(_merge_findings(group))

    return clusters


def build_llm_candidate_groups(
    clusters: list[FindingCluster],
) -> list[list[FindingCluster]]:
    """Group clusters that might be duplicates for LLM review."""
    by_category: dict[str, list[FindingCluster]] = defaultdict(list)
    for cluster in clusters:
        by_category[cluster.finding.get("category", "")].append(cluster)

    groups: list[list[FindingCluster]] = []
    for category_clusters in by_category.values():
        if len(category_clusters) < 2:
            continue

        parent = list(range(len(category_clusters)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for i, left in enumerate(category_clusters):
            left_path = _norm_path(left.finding.get("file_path"))
            left_title = left.finding.get("title", "")
            for j in range(i + 1, len(category_clusters)):
                right = category_clusters[j]
                right_path = _norm_path(right.finding.get("file_path"))
                right_title = right.finding.get("title", "")
                same_file = bool(left_path and left_path == right_path)
                similar_title = (
                    _title_ratio(left_title, right_title) >= CANDIDATE_DUPE_THRESHOLD
                )
                if same_file or similar_title:
                    union(i, j)

        components: dict[int, list[FindingCluster]] = defaultdict(list)
        for index, cluster in enumerate(category_clusters):
            components[find(index)].append(cluster)

        for component in components.values():
            if len(component) >= 2:
                groups.append(component)

    return groups


def _clusters_not_in_groups(
    clusters: list[FindingCluster],
    groups: list[list[FindingCluster]],
) -> list[FindingCluster]:
    grouped_ids: set[str] = set()
    for group in groups:
        for cluster in group:
            grouped_ids.update(cluster.source_ids)
    return [
        cluster
        for cluster in clusters
        if not any(source_id in grouped_ids for source_id in cluster.source_ids)
    ]


def _merge_cluster_list(clusters: list[FindingCluster]) -> FindingCluster:
    findings = [cluster.finding for cluster in clusters]
    merged = _merge_findings(findings)
    for cluster in clusters:
        for persona in cluster.personas:
            if persona and persona not in merged.personas:
                merged.personas.append(persona)
        for source_id in cluster.source_ids:
            if source_id and source_id not in merged.source_ids:
                merged.source_ids.append(source_id)
    return merged


def _load_groups_json(text: str) -> list:
    """Find {"groups": [...]} (or a bare [[...]]) in a model reply."""
    text = re.sub(r"```(?:json)?", "", text)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            payload, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("groups"), list):
            return payload["groups"]
        if isinstance(payload, list) and all(isinstance(g, list) for g in payload):
            return payload
    raise ValueError(f"No groups JSON in LLM response: {text[:200]!r}")


def _parse_llm_merge_response(text: str, aliases: dict[str, str]) -> list[list[str]]:
    """Return groups of source ids; `aliases` maps prompt ids to source ids."""
    parsed: list[list[str]] = []
    for entry in _load_groups_json(text):
        if not isinstance(entry, list):
            continue
        ids = list(dict.fromkeys(aliases[a] for a in map(str, entry) if a in aliases))
        if len(ids) >= 2:
            parsed.append(ids)
    return parsed


async def llm_merge_candidate_groups(
    client,
    model: str,
    groups: list[list[FindingCluster]],
) -> list[FindingCluster]:
    """Ask the LLM which clusters in each group describe the same issue."""
    if not groups:
        return []

    merged: list[FindingCluster] = []
    for group in groups:
        # Short ids keep the JSON answer small; real ids are UUIDs.
        aliases = {
            f"f{n}": cluster.source_ids[0]
            for n, cluster in enumerate(group, 1)
            if cluster.source_ids
        }
        alias_of = {source: alias for alias, source in aliases.items()}
        lines = []
        for cluster in group:
            if not cluster.source_ids:
                continue
            finding = cluster.finding
            lines.append(
                "\n".join(
                    [
                        f"- id: {alias_of[cluster.source_ids[0]]}",
                        f"  title: {finding.get('title', '')}",
                        f"  description: {finding.get('description', '')}",
                        f"  file_path: {finding.get('file_path') or '(none)'}",
                        f"  personas: {', '.join(cluster.personas)}",
                    ]
                )
            )

        prompt = (
            "You deduplicate developer-experience findings.\n"
            "Findings in this group may or may not describe the same underlying issue.\n"
            "Return JSON only:\n"
            '{"groups": [["f1", "f2"], ["f3"]]}\n'
            "Rules:\n"
            "- Put IDs together only when they clearly describe the same issue.\n"
            "- Do not merge related but distinct issues.\n"
            "- Omit singletons.\n\n"
            f"Category: {group[0].finding.get('category', '')}\n"
            + "\n".join(lines)
        )

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=2048,
                system=(
                    "You are a precise deduplication assistant. "
                    "Respond with valid JSON only."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text") and block.text
            ]
            merge_groups = _parse_llm_merge_response("\n".join(text_parts), aliases)
        except Exception:
            logger.warning("LLM dedup failed for category group", exc_info=True)
            merged.extend(group)
            continue

        merged_ids: set[str] = set()
        for id_group in merge_groups:
            selected = [
                cluster
                for cluster in group
                if cluster.source_ids and cluster.source_ids[0] in id_group
            ]
            if len(selected) >= 2:
                merged.append(_merge_cluster_list(selected))
                merged_ids.update(id_group)

        for cluster in group:
            source_id = cluster.source_ids[0] if cluster.source_ids else ""
            if source_id not in merged_ids:
                merged.append(cluster)

    return merged


async def deduplicate_findings(
    findings: list[dict],
    client=None,
    model: str | None = None,
) -> list[FindingCluster]:
    """Conservative merge, then optional LLM merge on candidate groups."""
    obvious = conservative_merge(findings)
    candidate_groups = build_llm_candidate_groups(obvious)
    untouched = _clusters_not_in_groups(obvious, candidate_groups)

    if not candidate_groups or client is None or not model:
        return obvious

    llm_merged = await llm_merge_candidate_groups(client, model, candidate_groups)
    return untouched + llm_merged
