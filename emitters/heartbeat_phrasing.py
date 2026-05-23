"""
Per-agent per-state heartbeat phrasing registry (CONTEXT.md §5).

Rules:
  - Professional / operational tone ONLY
  - NEVER anthropomorphic theater ('AI analyzing...', 'AI thinking deeply...', etc.)
  - 14 agents × 4 states × 3 phrasings (rotating to avoid monotony)
  - Forbidden phrases are checked at emit time by AgentTelemetryEmitter

All phrasings describe what the agent MONITORS or HAS DONE — not what it is
"feeling" or "thinking". Language: operational, terse, third-person optional.

Phase 66 v1: all 14 agents populated with ≥3 phrasings per state.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Forbidden phrases — NEVER allowed in any agent telemetry text
# ─────────────────────────────────────────────────────────────────────────────

FORBIDDEN_PHRASES: list[str] = [
    "AI analyzing market",
    "AI thinking deeply",
    "AI is processing",
    "analyzing with AI",
    "deep AI analysis",
    "AI senses",
    "AI feeling",
    "AI exploring",
    "AI contemplating",
    "AI pondering",
    "analyzing your",
    "thinking about",
    "AI analyzing",
    "AI thinking",
]


# ─────────────────────────────────────────────────────────────────────────────
# Heartbeat phrasing registry
# key: (agent_id, state) — values are 3-element rotation lists
# state values: "pre" | "open" | "mid" | "close"
# ─────────────────────────────────────────────────────────────────────────────

HEARTBEAT_PHRASINGS: dict[tuple[str, str], list[str]] = {
    # ── macro-agent ──────────────────────────────────────────────────────────
    ("macro-agent", "pre"): [
        "monitoring overnight macro releases",
        "pre-market catalyst calendar synced",
        "macro context refresh queued",
    ],
    ("macro-agent", "open"): [
        "monitoring scheduled catalysts",
        "tracking macro divergence",
        "macro surprise threshold engaged",
    ],
    ("macro-agent", "mid"): [
        "monitoring scheduled catalysts",
        "macro context stable",
        "tracking macro divergence",
    ],
    ("macro-agent", "close"): [
        "recapping macro releases",
        "post-close macro context stable",
        "preparing overnight macro brief",
    ],

    # ── briefing-agent ───────────────────────────────────────────────────────
    ("briefing-agent", "pre"): [
        "monitoring overnight gaps",
        "preparing pre-market brief",
        "reviewing readiness signals",
    ],
    ("briefing-agent", "open"): [
        "session brief active",
        "monitoring opening range formation",
        "briefing context updated",
    ],
    ("briefing-agent", "mid"): [
        "mid-session brief stable",
        "monitoring intra-day context shift",
        "briefing data current",
    ],
    ("briefing-agent", "close"): [
        "compiling session recap",
        "post-session brief pending",
        "end-of-day briefing queued",
    ],

    # ── calendar-agent ───────────────────────────────────────────────────────
    ("calendar-agent", "pre"): [
        "economic calendar loaded for session",
        "monitoring next-24h events",
        "calendar sync complete",
    ],
    ("calendar-agent", "open"): [
        "calendar tracking active",
        "monitoring event countdown",
        "next catalyst window computed",
    ],
    ("calendar-agent", "mid"): [
        "calendar monitoring active",
        "tracking remaining events",
        "countdown timers running",
    ],
    ("calendar-agent", "close"): [
        "calendar wrap-up in progress",
        "reviewing released events",
        "post-session calendar audit done",
    ],

    # ── liquidity-agent ──────────────────────────────────────────────────────
    ("liquidity-agent", "pre"): [
        "scanning pre-market liquidity zones",
        "liquidity map refresh queued",
        "monitoring overnight order flow",
    ],
    ("liquidity-agent", "open"): [
        "liquidity sweep monitoring active",
        "tracking orderbook depth",
        "monitoring high-value nodes",
    ],
    ("liquidity-agent", "mid"): [
        "liquidity context stable",
        "monitoring sweep candidates",
        "orderbook depth tracking active",
    ],
    ("liquidity-agent", "close"): [
        "end-of-session liquidity audit",
        "post-close orderbook review",
        "liquidity map finalizing",
    ],

    # ── readiness-agent ──────────────────────────────────────────────────────
    ("readiness-agent", "pre"): [
        "readiness checklist monitoring active",
        "pre-session readiness scan complete",
        "evaluating session readiness signals",
    ],
    ("readiness-agent", "open"): [
        "session readiness confirmed",
        "monitoring execution readiness",
        "readiness context stable",
    ],
    ("readiness-agent", "mid"): [
        "mid-session readiness stable",
        "monitoring fatigue indicators",
        "readiness score current",
    ],
    ("readiness-agent", "close"): [
        "post-session readiness review",
        "session readiness audit complete",
        "readiness log finalized",
    ],

    # ── pattern-engine ───────────────────────────────────────────────────────
    ("pattern-engine", "pre"): [
        "pattern library pre-loaded",
        "monitoring pre-market structure",
        "pattern context refresh complete",
    ],
    ("pattern-engine", "open"): [
        "pattern detection active",
        "monitoring structure formations",
        "real-time pattern scan running",
    ],
    ("pattern-engine", "mid"): [
        "pattern monitoring active",
        "tracking continuation signals",
        "structure analysis current",
    ],
    ("pattern-engine", "close"): [
        "end-of-session pattern audit",
        "reviewing session patterns",
        "pattern library update queued",
    ],

    # ── attention-engine ─────────────────────────────────────────────────────
    ("attention-engine", "pre"): [
        "attention focus pre-computed",
        "monitoring pre-session relevance signals",
        "attention weights updated",
    ],
    ("attention-engine", "open"): [
        "attention routing active",
        "monitoring cross-asset correlation",
        "focus scoring current",
    ],
    ("attention-engine", "mid"): [
        "attention scoring stable",
        "monitoring relevance drift",
        "focus map current",
    ],
    ("attention-engine", "close"): [
        "end-of-session attention audit",
        "reviewing focus signals",
        "attention report queued",
    ],

    # ── risk-agent ───────────────────────────────────────────────────────────
    ("risk-agent", "pre"): [
        "pre-session risk baseline computed",
        "monitoring portfolio exposure",
        "risk thresholds loaded",
    ],
    ("risk-agent", "open"): [
        "risk monitoring active",
        "exposure check running",
        "real-time drawdown tracking",
    ],
    ("risk-agent", "mid"): [
        "risk context stable",
        "monitoring drawdown level",
        "position risk current",
    ],
    ("risk-agent", "close"): [
        "end-of-session risk report",
        "reviewing daily risk metrics",
        "drawdown audit complete",
    ],

    # ── session-agent ────────────────────────────────────────────────────────
    ("session-agent", "pre"): [
        "session state pre-computed",
        "monitoring pre-session conditions",
        "session context loaded",
    ],
    ("session-agent", "open"): [
        "session monitoring active",
        "tracking session window",
        "open session context stable",
    ],
    ("session-agent", "mid"): [
        "mid-session context stable",
        "monitoring session transitions",
        "session state current",
    ],
    ("session-agent", "close"): [
        "session close detected",
        "post-session state logged",
        "session context finalized",
    ],

    # ── replay-engine ────────────────────────────────────────────────────────
    ("replay-engine", "pre"): [
        "replay context loaded from prior session",
        "monitoring pre-session replay candidates",
        "replay queue initialized",
    ],
    ("replay-engine", "open"): [
        "replay engine monitoring",
        "tracking execution candidates for replay",
        "replay context current",
    ],
    ("replay-engine", "mid"): [
        "replay monitoring active",
        "logging session for replay",
        "replay capture running",
    ],
    ("replay-engine", "close"): [
        "session replay indexed",
        "replay archive updated",
        "post-session replay queued",
    ],

    # ── embeddings ───────────────────────────────────────────────────────────
    ("embeddings", "pre"): [
        "embedding cache pre-warmed",
        "monitoring embedding freshness",
        "vector index ready",
    ],
    ("embeddings", "open"): [
        "embedding service monitoring",
        "real-time embed queue processing",
        "vector similarity service ready",
    ],
    ("embeddings", "mid"): [
        "embedding service stable",
        "monitoring embed queue depth",
        "vector cache current",
    ],
    ("embeddings", "close"): [
        "end-of-session embed archive",
        "compressing embedding log",
        "embedding index finalized",
    ],

    # ── behavior-agent ───────────────────────────────────────────────────────
    ("behavior-agent", "pre"): [
        "behavioral baseline loaded",
        "monitoring pre-session behavior signals",
        "behavioral context refreshed",
    ],
    ("behavior-agent", "open"): [
        "behavioral monitoring active",
        "tracking execution discipline",
        "behavior context current",
    ],
    ("behavior-agent", "mid"): [
        "behavioral signals stable",
        "monitoring session discipline",
        "behavioral context current",
    ],
    ("behavior-agent", "close"): [
        "end-of-session behavioral audit",
        "reviewing session discipline metrics",
        "behavioral report queued",
    ],

    # ── journal-agent ────────────────────────────────────────────────────────
    ("journal-agent", "pre"): [
        "journal context loaded",
        "monitoring pre-session journal cues",
        "prior session review complete",
    ],
    ("journal-agent", "open"): [
        "journal tracking active",
        "logging session events",
        "journal context current",
    ],
    ("journal-agent", "mid"): [
        "journal monitoring active",
        "mid-session log up to date",
        "journal context stable",
    ],
    ("journal-agent", "close"): [
        "end-of-session journal finalized",
        "session log archived",
        "journal summary pending",
    ],

    # ── discovery-agent ──────────────────────────────────────────────────────
    ("discovery-agent", "pre"): [
        "discovery context pre-loaded",
        "monitoring cross-trade discovery candidates",
        "discovery pipeline initialized",
    ],
    ("discovery-agent", "open"): [
        "discovery monitoring active",
        "tracking emergent patterns",
        "discovery scan running",
    ],
    ("discovery-agent", "mid"): [
        "discovery monitoring active",
        "reviewing recent discoveries",
        "discovery context current",
    ],
    ("discovery-agent", "close"): [
        "end-of-session discovery audit",
        "discovery archive updated",
        "discovery report queued",
    ],
}


def get_phrasing(agent_id: str, state: str, iteration: int = 0) -> str:
    """Pull deterministic phrasing for (agent, state).

    Iteration rotates phrasings to avoid monotony in the UI.
    Falls back to generic operational phrasing when (agent_id, state) not found.

    Args:
        agent_id:  One of the 14 locked agent IDs.
        state:     Trading session state (pre/open/mid/close).
        iteration: Rotation index (e.g., heartbeat tick counter % 3).

    Returns:
        A phrasing string — NEVER contains a forbidden phrase.
    """
    phrasings = HEARTBEAT_PHRASINGS.get(
        (agent_id, state.lower()),
        [f"{agent_id} monitoring system state"],  # safe fallback
    )
    return phrasings[iteration % len(phrasings)]
