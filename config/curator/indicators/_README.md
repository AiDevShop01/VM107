# Curator Layer — Economic Indicator YAMLs

Phase 88.1 Plan 08. Layer 1 of the 3-layer AI Description architecture.

## Purpose

These YAMLs are the **permanent source of truth** for static indicator metadata.
- Curators own: name, unit, source agency, category, frequency, short_description, why_it_matters, affected_assets.
- AI owns: current_narrative, trading_implications, recent_changes, confidence (Layer 2).
- Frontend merges both at render time (Layer 3).

**AI NEVER writes to these YAMLs.**

## Schema

Each YAML file is named `{INDICATOR_ID}.yaml` (e.g., `CPIAUCSL.yaml`).

Required fields:
```yaml
indicator_id: str        # FRED series code or canonical ID
name: str                # Full indicator name
category: str            # e.g. inflation, employment, monetary_policy
frequency: str           # e.g. monthly, weekly, daily
country: str             # ISO country code (e.g. US)
importance: str          # critical | high | medium | low
short_description: str   # 1–2 sentence plain-English summary
why_it_matters: str      # Why traders and analysts track this indicator
affected_assets: list    # Canonical asset IDs impacted by this indicator
```

## Tier-1 Indicators (Phase 88.1 — Plan 08 seed)

| File | Indicator | Category | Importance |
|------|-----------|----------|------------|
| CPIAUCSL.yaml | CPI All Urban Consumers | inflation | critical |
| PAYEMS.yaml | Nonfarm Payrolls | employment | critical |
| FEDFUNDS.yaml | Federal Funds Rate | monetary_policy | critical |

Remaining Tier-1 indicators (CPILFESL, GDPC1, ISM, UNRATE, M2SL, WALCL, DGS10, VIXCLS, OIL)
will be added in Phase 88.1 Plan 09 (regeneration sweep).
