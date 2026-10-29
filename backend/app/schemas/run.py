from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SCP_STYLE_URL = re.compile(r"^git@[A-Za-z0-9.-]+:[A-Za-z0-9._/~-]+$")
_FORBIDDEN_URL_CHARS = re.compile(r"[\s;&|$`<>\\'\"(){}*?!#]")


def validate_repo_url(url: str) -> str:
    url = url.strip()
    if not url or url.startswith("-") or _FORBIDDEN_URL_CHARS.search(url):
        raise ValueError("repo_url contains characters that are not allowed")
    if _SCP_STYLE_URL.match(url):
        return url
    allowed = {
        s.strip()
        for s in os.environ.get("SU_ALLOWED_REPO_SCHEMES", "https").split(",")
        if s.strip()
    }
    parsed = urlparse(url)
    if parsed.scheme not in allowed or not parsed.hostname:
        raise ValueError(
            f"repo_url must be a {' or '.join(sorted(allowed))} URL or git@host:path"
        )
    return url


class PersonaEnvironmentSpec(BaseModel):
    persona_id: uuid.UUID
    environment_id: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_environment_ids(cls, data: object) -> object:
        if isinstance(data, dict) and "environment_id" not in data:
            legacy_ids = data.get("environment_ids") or []
            if legacy_ids:
                data = {**data, "environment_id": legacy_ids[0]}
            data.pop("environment_ids", None)
        return data


class RunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    repo_url: str
    persona_environments: list[PersonaEnvironmentSpec]
    journey_id: uuid.UUID
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    config: dict = Field(default_factory=dict)

    @field_validator("repo_url")
    @classmethod
    def _check_repo_url(cls, v: str) -> str:
        return validate_repo_url(v)


class RunResponse(BaseModel):
    id: uuid.UUID
    name: str
    repo_url: str
    persona_environments: list[PersonaEnvironmentSpec]
    journey_id: uuid.UUID
    model: str
    config: dict
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    score: str | None
    score_rationale: str | None
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AgentStatusUpdate(BaseModel):
    persona_id: str
    current_phase: str


class AgentProgressUpdate(BaseModel):
    persona_id: str
    event_type: str
    message: str
    data: dict = Field(default_factory=dict)


class AgentDonePayload(BaseModel):
    persona_id: str
    status: str
    phase_summaries: dict = Field(default_factory=dict)
    findings: list[dict] = Field(default_factory=list)
    blocked_phase: str | None = None
    blocked_reason: str | None = None
    usage: dict = Field(default_factory=dict)
