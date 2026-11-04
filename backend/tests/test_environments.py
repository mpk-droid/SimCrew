from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.engine import runner
from app.engine.orchestrator import _unhealthy_message
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    image_policy_error,
)


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/mpk-droid/simcrew:latest",
        "quay.io/team/simcrew-fedora-go:1.2.3",
        "registry.example.com:5000/a/b",
        "simcrew",
        "ghcr.io/x/y@sha256:" + "a" * 64,
    ],
)
def test_accepts_image_references(image: str) -> None:
    assert EnvironmentCreate(name="n", image=image).image == image


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/x/y; rm -rf /",
        "ghcr.io/x/y:tag with space",
        "GHCR.IO/Upper/Case",
        "--privileged",
        "ghcr.io/x/$(id)",
        "",
    ],
)
def test_rejects_bad_image_references(image: str) -> None:
    with pytest.raises(ValidationError):
        EnvironmentCreate(name="n", image=image)


def test_allowlist_restricts_images(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SU_ALLOWED_ENV_IMAGE_PREFIXES", "ghcr.io/mpk-droid/, quay.io/ok/"
    )
    assert EnvironmentCreate(name="n", image="quay.io/ok/img:1").image
    with pytest.raises(ValidationError, match="not allowed"):
        EnvironmentCreate(name="n", image="docker.io/evil/miner:latest")
    with pytest.raises(ValidationError, match="not allowed"):
        EnvironmentUpdate(image="docker.io/evil/miner:latest")
    assert image_policy_error("docker.io/evil/miner") is not None


def test_no_allowlist_allows_any_valid_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SU_ALLOWED_ENV_IMAGE_PREFIXES", raising=False)
    assert image_policy_error("docker.io/anything/at-all:1") is None


def test_update_without_image_skips_validation() -> None:
    assert EnvironmentUpdate(description="new").image is None


def test_unhealthy_message_explains_environment_images() -> None:
    plain = _unhealthy_message({"name": "Sam"}, 120)
    assert "Sam" in plain and "FROM" not in plain
    custom = _unhealthy_message(
        {"name": "Sam (Go)", "environment_image": "quay.io/me/go:1"}, 120
    )
    assert "quay.io/me/go:1" in custom and "FROM the SimCrew agent image" in custom


def test_agent_prompt_never_includes_the_environment_description(monkeypatch) -> None:
    prompts: list[str] = []

    async def fake_phase(**kwargs) -> str:
        prompts.append(kwargs["system_prompt"])
        return "done"

    monkeypatch.setattr(runner, "_build_client", lambda config: object())
    monkeypatch.setattr(runner, "run_persona_phase", fake_phase)
    persona = {
        "id": "p1",
        "name": "Sam",
        "system_prompt": "You are Sam.",
        "environment_description": "Fresh laptop, no oc installed",
    }
    phases = [{"name": "setup", "instructions": "Set it up.", "order": 1}]

    asyncio.run(runner.execute_agent_run(persona, phases, "m", {}, "/tmp"))

    assert prompts == ["You are Sam."]
