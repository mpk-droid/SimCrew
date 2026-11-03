from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.run import RunPersona
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Severity(enum.Enum):
    critical = "critical"
    needs_attention = "needs_attention"
    nits = "nits"


SEVERITY_RANK = {
    Severity.critical: 2,
    Severity.needs_attention: 1,
    Severity.nits: 0,
}

_LEGACY_SEVERITY_MAP = {
    "high": Severity.needs_attention,
    "medium": Severity.needs_attention,
    "low": Severity.nits,
    "info": Severity.nits,
}


def normalize_severity(value: str) -> Severity:
    key = value.lower().strip().replace("-", "_").replace(" ", "_")
    if key in _LEGACY_SEVERITY_MAP:
        return _LEGACY_SEVERITY_MAP[key]
    return Severity(key)


def normalize_line_range(value: object) -> list[int] | None:
    """Coerce whatever the model sent into [start, end], or None.

    The tool schema asks for two integers, but models also send 42, "42",
    "10-20", or one-item lists; a raw int crashed the ARRAY column insert.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return [int(value), int(value)]
    if isinstance(value, str):
        numbers = [int(n) for n in re.findall(r"\d+", value)][:2]
    elif isinstance(value, (list, tuple)):
        numbers = []
        for item in value[:2]:
            if isinstance(item, bool):
                return None
            try:
                numbers.append(int(item))
            except (TypeError, ValueError):
                return None
    else:
        return None
    if not numbers:
        return None
    return [numbers[0], numbers[-1]]


def normalize_file_path(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple)):
        return None
    path = str(value).strip()
    return path[:1024] or None


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_persona_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_personas.id", ondelete="CASCADE")
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    category: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line_range: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase: Mapped[str] = mapped_column(String(255))
    run_persona: Mapped["RunPersona"] = relationship(
        "RunPersona", back_populates="findings"
    )
