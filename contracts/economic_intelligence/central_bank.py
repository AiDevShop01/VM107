"""CentralBankSection — Phase 94 §J.

Tracks central bank stance, policy rate, balance sheet, and summarised
latest statement. statement_summary is LLM-generated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class CentralBankStance(str, Enum):
    """Coarse 5-bucket stance taxonomy."""

    HAWKISH = "HAWKISH"
    HAWKISH_HOLD = "HAWKISH_HOLD"
    NEUTRAL = "NEUTRAL"
    DOVISH_HOLD = "DOVISH_HOLD"
    DOVISH = "DOVISH"


class CentralBankStatement(BaseModel):
    """A single central bank statement / decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str = Field(min_length=1)
    issued_at: datetime
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    citations: list[str] = Field(
        description="Citation grammar refs to source statement / speech.",
    )


class CentralBankSection(BaseSection):
    """Central bank stance + recent statements."""

    bank: str = Field(
        min_length=1,
        description="Central bank ID (e.g., 'FED', 'ECB').",
    )
    stance: CentralBankStance
    policy_rate: float
    balance_sheet_usd_bn: float | None = Field(
        default=None,
        description="Balance sheet size in $bn (None if not applicable).",
    )
    latest_statement: CentralBankStatement | None = None
