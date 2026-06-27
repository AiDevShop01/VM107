"""CrossAssetSection — Phase 94 §Q.

Snapshot of cross-asset levels (FX, rates, equity, commodities) at the time
the EconomicSnapshot was generated.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base_section import BaseSection


class AssetLevel(BaseModel):
    """A single asset price/level snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(min_length=1)
    level: float
    change_1d: float
    change_1w: float


class CrossAssetSection(BaseSection):
    """Cross-asset section payload."""

    assets: list[AssetLevel]
