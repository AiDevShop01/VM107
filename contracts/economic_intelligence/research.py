"""ResearchSection — Phase 94 §L.

Curated short-form research items surfaced to the situation room. Pulled
from the Phase 92 research platform.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class ResearchItem(BaseModel):
    """A single research item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    published_at: datetime
    author: str = Field(min_length=1)
    citations: list[str]


class ResearchSection(BaseSection):
    """Research feed section."""

    items: list[ResearchItem]
