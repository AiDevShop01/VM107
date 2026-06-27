"""Phase 94-06 — ThemeMonitor agent tests.

Locks per §H.4:

* Ranking is Strength × Confidence (NEVER strength alone).
* ARCHIVED themes are filtered out before ranking.
* Section themes list clipped to 5..7 entries.
"""

from __future__ import annotations

from agents.theme_monitor import ThemeMonitor
from contracts.economic_intelligence.themes import Theme, ThemeMonitorSection, ThemeState


def _theme(theme_id: str, strength: float, state: ThemeState = ThemeState.STABLE) -> Theme:
    return Theme(
        theme_id=theme_id,
        label=theme_id.replace("_", " ").title(),
        strength=strength,
        state=state,
        drivers=["indicator:DRV1", "indicator:DRV2"],
        first_seen="2026-06-01T00:00:00Z",
        last_changed="2026-06-26T00:00:00Z",
    )


def test_ranks_by_strength_times_confidence():
    """(80, 0.9), (85, 0.6), (70, 0.95) → ranked 72 > 66.5 > 51.

    theme1 strength=80 conf=0.9 score=72
    theme3 strength=70 conf=0.95 score=66.5
    theme2 strength=85 conf=0.6 score=51
    """
    monitor = ThemeMonitor()
    pairs = [
        (_theme("theme1", 80.0), 0.9),
        (_theme("theme2", 85.0), 0.6),
        (_theme("theme3", 70.0), 0.95),
    ]
    section = monitor.invoke(pairs, country="US")
    ranked_ids = [t.theme_id for t in section.themes]
    assert ranked_ids[:3] == ["theme1", "theme3", "theme2"]


def test_top_n_clipped_to_dashboard():
    """Section.themes is clipped to the 5..7 dashboard window per §H.4."""
    monitor = ThemeMonitor()
    # 12 themes with descending strength → clipped to 7.
    pairs = [
        (_theme(f"t{i:02d}", 100.0 - i * 5), 0.8)
        for i in range(12)
    ]
    section = monitor.invoke(pairs, country="US")
    assert isinstance(section, ThemeMonitorSection)
    assert 5 <= len(section.themes) <= 7


def test_archived_themes_filtered_out():
    monitor = ThemeMonitor()
    pairs = [
        (_theme("active1", 80.0, ThemeState.DOMINANT), 0.9),
        (_theme("archived1", 90.0, ThemeState.ARCHIVED), 0.95),
        (_theme("active2", 70.0, ThemeState.EMERGING), 0.7),
    ]
    section = monitor.invoke(pairs, country="US")
    ids = {t.theme_id for t in section.themes}
    assert "archived1" not in ids
    assert {"active1", "active2"} <= ids


def test_empty_input_returns_unavailable_status():
    monitor = ThemeMonitor()
    section = monitor.invoke([], country="US")
    assert section.status.value == "UNAVAILABLE"
    assert section.themes == []


def test_agent_id_is_canonical():
    assert ThemeMonitor.AGENT_ID == "vm107.theme_monitor"


def test_section_carries_strength_times_confidence_citations():
    monitor = ThemeMonitor()
    pairs = [(_theme("t1", 80.0), 0.9), (_theme("t2", 60.0), 0.7)]
    section = monitor.invoke(pairs, country="US")
    assert all(c.startswith("ref:theme:") for c in section.citations)
    assert "ref:theme:t1" in section.citations
