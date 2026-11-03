from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.engine.orchestrator import _unhealthy_message
from app.engine.prompt_generator import generate_system_prompt, with_environment
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


def _prompt() -> str:
    return generate_system_prompt("Sam", "a junior dev", "clarity", "new to AI")


def test_environment_is_added_to_the_environment_section() -> None:
    prompt = with_environment(_prompt(), "Fedora 40 with Go installed.")
    assert (
        "## Your Environment\nYour machine: Fedora 40 with Go installed. You have"
        in (prompt)
    )
    assert prompt.count("Your machine:") == 1


def test_environment_section_is_appended_when_missing() -> None:
    prompt = with_environment("You are Sam.", "Ubuntu 24.04")
    assert prompt.endswith("## Your Environment\nYour machine: Ubuntu 24.04.")


@pytest.mark.parametrize("description", [None, "", "   "])
def test_no_environment_leaves_prompt_unchanged(description: str | None) -> None:
    assert with_environment(_prompt(), description) == _prompt()


def test_unhealthy_message_explains_environment_images() -> None:
    plain = _unhealthy_message({"name": "Sam"}, 120)
    assert "Sam" in plain and "FROM" not in plain
    custom = _unhealthy_message(
        {"name": "Sam (Go)", "environment_image": "quay.io/me/go:1"}, 120
    )
    assert "quay.io/me/go:1" in custom and "FROM the SimCrew agent image" in custom
