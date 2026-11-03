from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.engine.triage_dedup import (
    FindingCluster,
    _parse_llm_merge_response,
    llm_merge_candidate_groups,
)

ALIASES = {"f1": "uuid-1", "f2": "uuid-2", "f3": "uuid-3"}


@pytest.mark.parametrize(
    "reply",
    [
        '{"groups": [["f1", "f2"]]}',
        '```json\n{"groups": [["f1", "f2"]]}\n```',
        'Here you go: {"groups": [["f1", "f2"]]} Hope that helps {not json}',
        '[["f1", "f2"]]',
    ],
)
def test_parses_groups_in_common_reply_shapes(reply: str) -> None:
    assert _parse_llm_merge_response(reply, ALIASES) == [["uuid-1", "uuid-2"]]


def test_unknown_ids_and_singletons_are_dropped() -> None:
    reply = '{"groups": [["f1", "zz"], ["f2", "f3", "f3"], ["f1"]]}'
    assert _parse_llm_merge_response(reply, ALIASES) == [["uuid-2", "uuid-3"]]


@pytest.mark.parametrize("reply", ["", '{"groups": [["f1", "f2"]', "no json here"])
def test_truncated_or_missing_json_raises(reply: str) -> None:
    with pytest.raises(ValueError, match="No groups JSON"):
        _parse_llm_merge_response(reply, ALIASES)


class _FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.messages = self

    async def create(self, **kwargs) -> SimpleNamespace:
        self.prompts.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(text=self.reply)])


def _cluster(title: str) -> FindingCluster:
    return FindingCluster(
        finding={"title": title, "description": "d", "category": "setup"},
        personas=["Sam"],
        source_ids=[str(uuid.uuid4())],
    )


def test_prompt_uses_short_ids_and_merge_maps_back() -> None:
    group = [
        _cluster("requirements.txt missing"),
        _cluster("make install fails"),
        _cluster("wrong port"),
    ]
    client = _FakeClient('{"groups": [["f1", "f2"]]}')

    merged = asyncio.run(llm_merge_candidate_groups(client, "m", [group]))

    prompt = client.prompts[0]
    assert "- id: f1" in prompt and group[0].source_ids[0] not in prompt
    assert len(merged) == 2
    combined = next(c for c in merged if len(c.source_ids) == 2)
    assert set(combined.source_ids) == {group[0].source_ids[0], group[1].source_ids[0]}
