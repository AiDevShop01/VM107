"""Phase 86 Plan 07 — macro_historical_analyst prompt template.

Locked decisions referenced:
- D5 (CONTEXT.md): event-driven, single emit, terminates
- D7: no Brain B5/B6/B9/B13; pure factual narration
- ARCHITECTURE §6: narrative MUST contain str(sample_size) AND period

The prompt template enforces:
1. Explicit N citation (exact integer) — required by regex assertion in agent.py
2. Explicit period citation (exact YYYY-YYYY string) — required by regex assertion
3. <= 50 word cap — enforced by narrative assertion (plan must_have)
4. No forecast language, no speculation — factual summary only
"""
from __future__ import annotations


INSTRUCTIONS = """You are a public macro-historical analyst. You are given an
event-study envelope: indicator, surprise threshold, sample size N, period
covered, and per-asset response curves (mean / median / IQR per day_offset).

Emit ONE paragraph (50 words or fewer) that:
1. EXPLICITLY cites the sample size N — use the exact integer.
2. EXPLICITLY cites the period — use the exact YYYY-YYYY string.
3. Summarizes the strongest cross-asset response (largest |mean| at any
   day_offset in [0..+10]).
4. Stays factual — no forecast language, no "this suggests", no speculation.

Do NOT include caveats, disclaimers, or recommendations. Do NOT invent numbers
not present in the envelope. Do NOT exceed 50 words."""


EXAMPLE = (
    "Looking at the 25 CPI beats above 0.3% since 1990-2025, Gold averaged "
    "-1.2% over the 5 days post-release; USD averaged +0.6%; SPX averaged -0.4%."
)


def _build_curve_digest(result: dict, asset_names: list[str]) -> str:
    """Format the response curves into a compact textual digest for the prompt."""
    curves = result.get("curves", [])
    asset_name_map: dict[str, str] = {}
    for i, curve in enumerate(curves):
        asset_id = curve.get("asset_id", f"asset_{i}")
        display_name = asset_names[i] if i < len(asset_names) else asset_id
        asset_name_map[asset_id] = display_name

    lines = []
    for curve in curves:
        asset_id = curve.get("asset_id", "?")
        name = asset_name_map.get(asset_id, asset_id)
        points = curve.get("points", [])
        if not points:
            continue
        # Find strongest response (largest |mean|)
        strongest = max(points, key=lambda p: abs(p.get("mean", 0.0)))
        day = strongest.get("day_offset", "?")
        mean = strongest.get("mean", 0.0)
        lines.append(f"  {name}: strongest mean={mean:+.2f}% at day_offset={day}")

    return "\n".join(lines) if lines else "  (no curve data)"


def build_prompt(
    envelope: dict,
    indicator_name: str,
    asset_names: list[str],
    result: dict,
) -> str:
    """Build the full prompt for the macro_historical_analyst agent.

    Args:
        envelope:       The vm102_event_study envelope (contains provenance with N + period).
        indicator_name: Human-readable indicator name, e.g. "Consumer Price Index".
        asset_names:    Ordered list of asset display names, e.g. ["Gold", "USD", "S&P 500"].
        result:         The result dict from the event-study response (contains curves).

    Returns:
        Full prompt string ready for LLM call.
    """
    prov = envelope.get("provenance", {})
    n = prov["sample_size"]
    period = prov["period"]
    threshold = prov.get("threshold", "N/A")

    curve_digest = _build_curve_digest(result, asset_names)

    return (
        f"{INSTRUCTIONS}\n\n"
        f"Example output (style reference — do NOT copy verbatim): {EXAMPLE}\n\n"
        f"Indicator: {indicator_name}\n"
        f"Surprise threshold: {threshold}\n"
        f"Sample size: N={n}\n"
        f"Period: {period}\n"
        f"Assets: {', '.join(asset_names)}\n"
        f"Response curves (strongest per asset):\n{curve_digest}\n\n"
        f"Emit your <=50-word paragraph now, citing N={n} and period={period} verbatim."
    )
