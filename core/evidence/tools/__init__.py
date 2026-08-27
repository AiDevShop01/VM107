"""Budgeted tool surface (Phase 168, AGV-07 / D-04).

- ``budget``: token estimator, Contract §6 per-tier caps, effective-cap
  (min of tier + profile) enforcement, and the L0->L4 progressive-disclosure
  ladder helpers.
- ``quant_tools``: budgeted ``ToolResultEnvelope`` wrappers over the reuse-first
  VM102 quant reads (percentile/zscore, change-point, surprise, correlation/
  lead-lag) — a scalar/struct back, never the underlying series.
"""
