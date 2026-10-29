from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.engine import nvidia_nim
from app.engine.nvidia_nim import NvidiaNimMessages

OK = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}


def _client(statuses: list[int], seen: list[str]) -> NvidiaNimMessages:
    replies = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["model"])
        status = next(replies)
        return httpx.Response(status, json=OK if status == 200 else {"error": "x"})

    nim = NvidiaNimMessages(
        base_url="https://nim.test/v1",
        api_key="k",
        default_model="primary",
        fallback_model="fallback",
    )
    nim._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return nim


def _call(nim: NvidiaNimMessages):
    return asyncio.run(
        nim.create(model="primary", max_tokens=10, system="s", messages=[])
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(nvidia_nim.asyncio, "sleep", instant)


def test_transient_404_is_retried() -> None:
    seen: list[str] = []
    result = _call(_client([404, 200], seen))
    assert result.content[0].text == "hi"
    assert seen == ["primary", "primary"]


def test_persistent_404_falls_back_to_second_model() -> None:
    seen: list[str] = []
    statuses = [404] * nvidia_nim.MAX_RETRIES + [200]
    result = _call(_client(statuses, seen))
    assert result.content[0].text == "hi"
    assert seen[-1] == "fallback"


def test_client_errors_other_than_404_fail_fast() -> None:
    seen: list[str] = []
    with pytest.raises(httpx.HTTPStatusError):
        _call(_client([400], seen))
    assert seen == ["primary"]
