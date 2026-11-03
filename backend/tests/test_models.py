from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from pydantic import ValidationError

from app.engine import runner
from app.schemas.run import RunCreate


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "NVIDIA_API_KEY",
        "NVIDIA_NIM_MODEL",
        "NVIDIA_NIM_BASE_URL",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    runner._model_list_cache.clear()


def test_default_is_the_configured_nim_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setenv("NVIDIA_NIM_MODEL", "rits/deepseek-ai/DeepSeek-V4.1-Flash-1017")
    assert runner.default_model({}) == "rits/deepseek-ai/DeepSeek-V4.1-Flash-1017"


def test_default_without_nim_is_a_claude_model(monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner.default_model({}) == runner.DEFAULT_ANTHROPIC_MODEL
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    assert runner.default_model({}) == "claude-opus-5-5"


def test_run_config_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    assert runner.default_model({"nvidia_nim_model": "from-config"}) == "from-config"


def _run(model):
    return RunCreate(
        name="t",
        repo_url="https://github.com/a/b.git",
        persona_environments=[],
        journey_id=uuid.uuid4(),
        model=model,
    )


@pytest.mark.parametrize(
    "model", ["rits/zai-org/glm-5-3", "claude-sonnet-5-5", "org/model:tag", "a/b@v1"]
)
def test_accepts_model_ids(model: str) -> None:
    assert _run(model).model == model


@pytest.mark.parametrize("model", [None, "", "   "])
def test_blank_model_means_server_default(model) -> None:
    assert _run(model).model is None


@pytest.mark.parametrize("model", ["two words", "x; rm -rf /", "-flag", "a" * 300])
def test_rejects_bad_model_ids(model: str) -> None:
    with pytest.raises(ValidationError):
        _run(model)


def _fake_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner.httpx, "AsyncClient", factory)


def test_lists_and_caches_provider_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": [{"id": "b/two"}, {"id": "a/one"}]})

    _fake_client(monkeypatch, handler)
    assert asyncio.run(runner.list_models({})) == ["a/one", "b/two"]
    assert asyncio.run(runner.list_models({})) == ["a/one", "b/two"]
    assert calls == ["/v1/models"]


def test_listing_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    _fake_client(monkeypatch, lambda request: httpx.Response(500))
    assert asyncio.run(runner.list_models({})) == []


def test_no_listing_without_nim_key() -> None:
    assert asyncio.run(runner.list_models({})) == []
