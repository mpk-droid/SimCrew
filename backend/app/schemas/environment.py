from __future__ import annotations

import os
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# registry/path[:tag][@sha256:digest]; no whitespace, no shell metacharacters.
_IMAGE_REF = re.compile(
    r"^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]+)?"
    r"(/[a-z0-9]+([._-][a-z0-9]+)*)*"
    r"(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
    r"(@sha256:[a-f0-9]{64})?$"
)


def allowed_image_prefixes() -> list[str]:
    raw = os.environ.get("SU_ALLOWED_ENV_IMAGE_PREFIXES", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def image_policy_error(image: str) -> str | None:
    """Why `image` may not be used as an agent environment, or None if it may."""
    prefixes = allowed_image_prefixes()
    if prefixes and not any(image.startswith(p) for p in prefixes):
        return (
            f"Image {image} is not allowed on this SimCrew instance. "
            f"Allowed prefixes: {', '.join(prefixes)}"
        )
    return None


def validate_image(image: str) -> str:
    image = image.strip()
    if len(image) > 2048 or not _IMAGE_REF.match(image):
        raise ValueError(
            "image must be a container image reference like "
            "ghcr.io/org/name:tag (lowercase, no spaces)"
        )
    if error := image_policy_error(image):
        raise ValueError(error)
    return image


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    image: str = Field(..., min_length=1)
    description: str | None = None

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: str) -> str:
        return validate_image(v)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    image: str | None = None
    description: str | None = None

    @field_validator("image")
    @classmethod
    def _check_image(cls, v: str | None) -> str | None:
        return None if v is None else validate_image(v)


class EnvironmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    image: str
    description: str | None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
