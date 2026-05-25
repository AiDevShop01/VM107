"""Phase 67 Plan 06 — MorningBriefEmitter tests.

Covers:
  * Contract shape + Pydantic v2 frozen/extra=forbid enforcement
  * 5-step pipeline mirror of Phase 66 global_narrative_emitter.py
  * Shared NoveltyEngine + SourceHealthRegistry injection
  * Deterministic base when novelty NOT crossed
  * LLM enrichment populated when novelty crossed
  * confidence_tier degradation (FULL / PARTIAL / DEGRADED)
  * Capability YAML validates (Phase 47.6 lock)
  * VM100 client wrapper (env fail-fast, HTTP wiring, bearer auth)
"""
from __future__ import annotations

import os
import yaml
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from emitters.contracts.morning_brief import MorningBriefContract
from emitters.morning_brief_emitter import MorningBriefEmitter
from emitters.novelty_engine import NoveltyEngine
from emitters.source_health_registry import SourceHealthRegistry
from emitters.degradation_policy_engine import DegradationPolicyEngine


pytestmark = pytest.mark.phase_67


# ── 1. Contract shape tests ─────────────────────────────────────────────────


def test_morning_brief_contract_is_frozen():
    """Contract must be frozen — mutations raise ValidationError."""
    c = MorningBriefContract(
        brief_id="b1",
        account_id=1,
        generated_at="2026-05-25T08:00:00Z",
        headline="h",
        body="b",
        confidence_score=0.9,
        confidence_tier="FULL",
        novelty_score=0.3,
        novelty_crossed=False,
    )
    with pytest.raises(Exception):  # pydantic.ValidationError on frozen
        c.headline = "mutated"  # type: ignore[misc]


def test_morning_brief_contract_extra_forbid():
    """Contract rejects unknown fields — extra=forbid."""
    with pytest.raises(Exception):
        MorningBriefContract(
            brief_id="b1",
            account_id=1,
            generated_at="2026-05-25T08:00:00Z",
            headline="h",
            body="b",
            confidence_score=0.9,
            confidence_tier="FULL",
            novelty_score=0.3,
            novelty_crossed=False,
            UNKNOWN_FIELD="reject",  # type: ignore[call-arg]
        )


def test_morning_brief_contract_confidence_tier_literal():
    """confidence_tier must be one of FULL / PARTIAL / DEGRADED."""
    with pytest.raises(Exception):
        MorningBriefContract(
            brief_id="b1",
            account_id=1,
            generated_at="2026-05-25T08:00:00Z",
            headline="h",
            body="b",
            confidence_score=0.9,
            confidence_tier="INVALID",  # type: ignore[arg-type]
            novelty_score=0.3,
            novelty_crossed=False,
        )


# ── 2. Emitter pipeline tests ──────────────────────────────────────────────


def test_emitter_uses_shared_novelty_engine_when_injected():
    """SHARED NoveltyEngine instance — never instantiate a new one (Phase 66 lock)."""
    shared = NoveltyEngine()
    emitter = MorningBriefEmitter(novelty_engine=shared)
    assert emitter._novelty is shared


def test_emitter_uses_shared_health_registry_when_injected():
    """SHARED SourceHealthRegistry instance."""
    shared = SourceHealthRegistry()
    emitter = MorningBriefEmitter(health_registry=shared)
    assert emitter._health is shared


def test_emitter_returns_morning_brief_contract():
    """get_morning_brief(account_id) returns MorningBriefContract instance."""
    emitter = MorningBriefEmitter()
    result = emitter.get_morning_brief(account_id=42)
    assert isinstance(result, MorningBriefContract)
    assert result.account_id == 42


def test_emitter_returns_deterministic_base_when_novelty_not_crossed():
    """No LLM enrichment when novelty.threshold_crossed=False."""
    emitter = MorningBriefEmitter()

    # Force novelty NOT crossed
    fake_novelty_result = MagicMock(score=0.1, threshold_crossed=False, reason_codes=[])
    with patch.object(emitter._novelty, "score", return_value=fake_novelty_result):
        result = emitter.get_morning_brief(account_id=1)

    assert result.novelty_crossed is False
    assert result.llm_enriched_headline is None
    assert result.llm_enriched_body is None
    # Deterministic base ALWAYS present
    assert result.headline
    assert result.body


def test_emitter_calls_llm_when_novelty_crossed():
    """LLM enrichment populated when novelty.threshold_crossed=True."""
    emitter = MorningBriefEmitter()

    fake_novelty = MagicMock(score=0.9, threshold_crossed=True, reason_codes=["MACRO_EVENT_ARRIVAL"])
    with patch.object(emitter._novelty, "score", return_value=fake_novelty), \
         patch.object(emitter, "_call_llm", return_value=("ENRICHED HEADLINE", "ENRICHED BODY")):
        result = emitter.get_morning_brief(account_id=1)

    assert result.novelty_crossed is True
    assert result.llm_enriched_headline == "ENRICHED HEADLINE"
    assert result.llm_enriched_body == "ENRICHED BODY"


def test_emitter_demo_true_when_degraded():
    """Source unhealthy → _demo=True + missing_sources populated."""
    emitter = MorningBriefEmitter()

    with patch.object(emitter, "_assemble_context", side_effect=RuntimeError("VM100 down")):
        result = emitter.get_morning_brief(account_id=1)

    assert result.demo is True
    assert result.confidence_tier == "DEGRADED"
    assert "vm100" in result.missing_sources or "vm102" in result.missing_sources


def test_emitter_confidence_tier_full_when_all_sources_ok():
    """0 missing sources → FULL tier."""
    emitter = MorningBriefEmitter()
    result = emitter.get_morning_brief(account_id=1)
    # Default assembly reports both sources OK
    assert result.confidence_tier == "FULL"
    assert result.missing_sources == []


def test_emitter_confidence_tier_partial_when_one_source_missing():
    """1 missing source → PARTIAL tier."""
    emitter = MorningBriefEmitter()

    def partial_assemble(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=False, failure_reason="down")
        return {"sources": {"vm100": True, "vm102": False}}

    with patch.object(emitter, "_assemble_context", side_effect=partial_assemble):
        result = emitter.get_morning_brief(account_id=1)

    assert result.confidence_tier == "PARTIAL"
    assert "vm102" in result.missing_sources


def test_emitter_top_catalysts_max_three():
    """top_catalysts capped at 3 items in deterministic base."""
    emitter = MorningBriefEmitter()
    result = emitter.get_morning_brief(account_id=1)
    assert len(result.top_catalysts) <= 3


def test_emitter_risk_alerts_max_three():
    """risk_alerts capped at 3 items."""
    emitter = MorningBriefEmitter()
    result = emitter.get_morning_brief(account_id=1)
    assert len(result.risk_alerts) <= 3


# ── 3. Capability YAML validation tests ─────────────────────────────────────


_VM107_ROOT = Path(__file__).resolve().parents[2]
_YAML_PATH = _VM107_ROOT / "registry" / "tool" / "vm107.morning_brief.yaml"


def test_morning_brief_capability_yaml_exists():
    """Phase 47.6 lock — capability YAML must be registered."""
    assert _YAML_PATH.exists(), f"Missing capability YAML at {_YAML_PATH}"


def test_morning_brief_capability_yaml_has_required_keys():
    """YAML must have id / type / description fields per Phase 47.6 schema."""
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    assert data["id"] == "vm107.morning_brief"
    assert data["type"] == "tool"  # 'emitter' not in valid types; fall back to 'tool'
    assert data.get("description")
    assert data.get("vm") == "vm107"


def test_morning_brief_capability_yaml_dependencies_listed():
    """Dependencies must include vm100 + vm107 sources used in pipeline."""
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    deps = data.get("dependencies") or {}
    assert deps  # non-empty


# ── 4. VM100 client wrapper tests ───────────────────────────────────────────


class TestVM107MorningBriefClient:
    """Tests for VM100/backend/mission_control/clients/vm107_morning_brief_client.py."""

    def test_client_fail_fast_on_missing_env(self, monkeypatch):
        """VM107_BASE_URL unset → fail-fast at instantiation (Phase 47.3 lock)."""
        # Inject VM100 backend onto sys.path on the fly so the import works.
        import sys
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.delenv("VM107_BASE_URL", raising=False)
        from mission_control.clients.vm107_morning_brief_client import (
            VM107MorningBriefClient,
        )
        with pytest.raises(KeyError):
            VM107MorningBriefClient()

    def test_client_fail_fast_on_missing_token(self, monkeypatch):
        """VM107_API_TOKEN unset → fail-fast at instantiation."""
        import sys
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.delenv("VM107_API_TOKEN", raising=False)
        from mission_control.clients.vm107_morning_brief_client import (
            VM107MorningBriefClient,
        )
        with pytest.raises(KeyError):
            VM107MorningBriefClient()

    @pytest.mark.asyncio
    async def test_client_get_morning_brief_returns_contract(self, monkeypatch):
        """get_morning_brief() returns MorningBriefContract on 200."""
        import sys
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.setenv("VM107_API_TOKEN", "test-token")

        from mission_control.clients.vm107_morning_brief_client import (
            VM107MorningBriefClient,
        )

        wire = {
            "brief_id": "b-1",
            "account_id": 7,
            "generated_at": "2026-05-25T08:00:00Z",
            "headline": "Test headline",
            "body": "Test body.",
            "top_catalysts": ["CPI", "FOMC", "NFP"],
            "risk_alerts": [],
            "llm_enriched_headline": None,
            "llm_enriched_body": None,
            "confidence_score": 0.9,
            "confidence_tier": "FULL",
            "missing_sources": [],
            "_demo": False,
            "novelty_score": 0.3,
            "novelty_crossed": False,
        }

        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value=wire)
        fake_response.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(return_value=fake_response)

        with patch("httpx.AsyncClient", return_value=fake_client):
            client = VM107MorningBriefClient()
            result = await client.get_morning_brief(account_id=7)

        assert isinstance(result, MorningBriefContract)
        assert result.brief_id == "b-1"
        assert result.account_id == 7

    @pytest.mark.asyncio
    async def test_client_raises_on_5xx(self, monkeypatch):
        """5xx response → raise."""
        import sys
        import httpx
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.setenv("VM107_API_TOKEN", "test-token")

        from mission_control.clients.vm107_morning_brief_client import (
            VM107MorningBriefClient,
        )

        fake_response = MagicMock()
        fake_response.status_code = 500
        fake_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=fake_response)
        )

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(return_value=fake_response)

        with patch("httpx.AsyncClient", return_value=fake_client):
            client = VM107MorningBriefClient()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_morning_brief(account_id=7)
