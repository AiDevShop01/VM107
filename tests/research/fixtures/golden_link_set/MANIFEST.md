# Phase 92 Plan 03 — Golden Link Set Manifest

30 hand-labelled documents used by the research classifier precision/recall harness.

| Source bucket | Count | Tier | Notes |
| ------------- | ----- | ---- | ----- |
| FOMC statements / minutes (Federal Reserve) | 10 | 1 | Stream B (RSS); fed_press_all / fed_speeches |
| ECB speeches / press releases               | 10 | 1 | Stream B (RSS); ecb_press / ecb_speeches |
| NBER working-paper abstracts                | 10 | 3 | Stream C (academic API); nber_papers |

## Labelling protocol

For each `<source>_<NN>.txt`, the `labels.yaml` entry records:

- `doc_id`     — filename without extension
- `source`     — fomc / ecb / nber
- `expected_indicators` — 1-3 FRED EconomicIndicator IDs the document should be linked to (from the Phase 83 catalog of 64 indicators — see VM107/tests/research/conftest.py `mock_economic_indicator_catalog` for the locked subset used in the host-shell run)
- `expected_assets`     — 1-4 asset IDs from `VM107/data/asset_universe.yaml` (DXY / GOLD / SPX / UST10Y / etc.)
- `expected_tier`       — 1 for FOMC + ECB, 3 for NBER
- `expected_status`     — `classified` for all 30 except docs designed to exercise the no-indicator-link soft-reject path (`unlinked`); the 30-doc split has 0 unlinked since every fixture was authored with at least one synonym hit. Soft-reject is exercised by a separate fixture in `test_classification_pipeline_e2e.py`.
- `expected_linker_stage` — `synonym` for the 25/30 with synonym-table-coverable terminology; `llm` for the 5/30 that ONLY mention LLM-fallback-only concepts (term premium, convenience yield, neutral rate, etc.)

## Source provenance

All FOMC/ECB/NBER bodies were authored as concise reformulations following the public-domain shape of:

- FOMC press releases (federalreserve.gov/newsevents/pressreleases.htm)
- ECB press releases (ecb.europa.eu/press/pr)
- NBER working-paper abstracts (nber.org/papers)

The textual content is composed by the test author to densely exercise the synonym table (Stage 1) and LLM fallback (Stage 2); no copying from copyrighted sources.

## Quarterly refresh

When refreshing this fixture set:

1. Keep the 25/5 synonym/LLM-fallback split (the precision/recall thresholds in `test_indicator_linker_precision_recall.py` are tuned to it).
2. Maintain ≥1 doc per Phase 83 indicator that has >5 mentions across the FOMC/ECB corpus (CPIAUCSL, UNRATE, PAYEMS, DGS10 minimum).
3. NBER abstracts should average ≥2 expected_indicators each (academic papers reference broader indicator clusters).
