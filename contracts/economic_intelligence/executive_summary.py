"""ExecutiveSummarySection — Phase 94 §E.

LLM-generated 30–60 word summary, regenerated only on HIGH+ events.
"""

from __future__ import annotations

from pydantic import Field

from .base_section import BaseSection


class ExecutiveSummarySection(BaseSection):
    """30–60 word executive summary."""

    summary: str = Field(
        min_length=1,
        description="30–60 word narrative summary.",
    )
    word_count: int = Field(
        ge=0,
        description="Word count of summary (for the 30..60 guardrail).",
    )
    headline_facts: list[str] = Field(
        description="3–5 bullet facts the summary is grounded in.",
    )
