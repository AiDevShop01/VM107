"""Phase 67 Plan 06 — OvernightDeltaEmitter tests.

Covers:
  * Contract shape + 4-bucket order lock
  * Direction + magnitude_label enum validation
  * _demo escalation rules (per-bucket → contract-level)
  * 5-step pipeline mirror (matches MorningBriefEmitter)
  * Capability YAML validates
  * VM100 client wrapper
  * Golden round-trip
"""
from __future__ import annotations

import json
import os
import yaml
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from emitters.contracts.overnight_delta import (
    BucketDelta,
    OvernightDeltaContract,
)
from emitters.overnight_delta_emitter import OvernightDeltaEmitter
from emitters.novelty_engine import NoveltyEngine
from emitters.source_health_registry import SourceHealthRegistry


pytestmark = pytest.mark.phase_67


# ── 1. Contract shape tests ─────────────────────────────────────────────────


def _bucket(name: str, **overrides) -> BucketDelta:
    defaults = dict(
        bucket=name,
        headline="OK",
        notable_symbols=[],
        direction="flat",
        magnitude_label="small",
        confidence=0.9,
    )
    defaults.update(overrides)
    return BucketDelta(**defaults)  # type: ignore[arg-type]


def test_overnight_delta_requires_exactly_4_buckets():
    """Validator rejects ≠4 bucket count."""
    with pytest.raises(Exception):
        OvernightDeltaContract(
            delta_id="d1",
            account_id=1,
            generated_at="2026-05-25T06:00:00Z",
            buckets=[_bucket("FX"), _bucket("BONDS"), _bucket("CRYPTO")],
            overall_summary="x",
            confidence_score=0.9,
            confidence_tier="FULL",
            novelty_score=0.1,
        )


def test_overnight_delta_requires_fixed_bucket_order():
    """Validator rejects wrong order (e.g. CRYPTO before COMMODITIES)."""
    with pytest.raises(Exception):
        OvernightDeltaContract(
            delta_id="d1",
            account_id=1,
            generated_at="2026-05-25T06:00:00Z",
            buckets=[
                _bucket("FX"),
                _bucket("BONDS"),
                _bucket("CRYPTO"),
                _bucket("COMMODITIES"),
            ],
            overall_summary="x",
            confidence_score=0.9,
            confidence_tier="FULL",
            novelty_score=0.1,
        )


def test_overnight_delta_accepts_fixed_order():
    c = OvernightDeltaContract(
        delta_id="d1",
        account_id=1,
        generated_at="2026-05-25T06:00:00Z",
        buckets=[
            _bucket("FX"),
            _bucket("BONDS"),
            _bucket("COMMODITIES"),
            _bucket("CRYPTO"),
        ],
        overall_summary="x",
        confidence_score=0.9,
        confidence_tier="FULL",
    )
    assert [b.bucket for b in c.buckets] == ["FX", "BONDS", "COMMODITIES", "CRYPTO"]


def test_bucket_direction_enum_enforced():
    with pytest.raises(Exception):
        _bucket("FX", direction="diagonal")  # type: ignore[arg-type]


def test_bucket_magnitude_enum_enforced():
    with pytest.raises(Exception):
        _bucket("FX", magnitude_label="gigantic")  # type: ignore[arg-type]


def test_contract_is_frozen():
    c = OvernightDeltaContract(
        delta_id="d1",
        account_id=1,
        generated_at="2026-05-25T06:00:00Z",
        buckets=[
            _bucket("FX"),
            _bucket("BONDS"),
            _bucket("COMMODITIES"),
            _bucket("CRYPTO"),
        ],
        overall_summary="x",
        confidence_score=0.9,
        confidence_tier="FULL",
    )
    with pytest.raises(Exception):
        c.overall_summary = "mutated"  # type: ignore[misc]


# ── 2. Emitter pipeline tests ──────────────────────────────────────────────


def test_emitter_returns_overnight_delta_contract():
    emitter = OvernightDeltaEmitter()
    result = emitter.get_overnight_delta(account_id=7)
    assert isinstance(result, OvernightDeltaContract)
    assert result.account_id == 7


def test_emitter_returns_4_buckets_in_order():
    emitter = OvernightDeltaEmitter()
    result = emitter.get_overnight_delta(account_id=1)
    assert [b.bucket for b in result.buckets] == ["FX", "BONDS", "COMMODITIES", "CRYPTO"]


def test_emitter_uses_shared_novelty_engine_when_injected():
    shared = NoveltyEngine()
    emitter = OvernightDeltaEmitter(novelty_engine=shared)
    assert emitter._novelty is shared


def test_emitter_uses_shared_health_registry_when_injected():
    shared = SourceHealthRegistry()
    emitter = OvernightDeltaEmitter(health_registry=shared)
    assert emitter._health is shared


def test_emitter_demo_top_level_true_when_all_buckets_demo():
    """If every bucket has _demo=True → contract-level _demo=True."""
    emitter = OvernightDeltaEmitter()

    # Force assemble_context to return no overnight data → all buckets demo
    with patch.object(emitter, "_assemble_context", return_value={}):
        result = emitter.get_overnight_delta(account_id=1)

    assert all(b.demo for b in result.buckets)
    assert result.demo is True


def test_emitter_demo_top_level_false_when_some_buckets_real():
    """At least one bucket with real data → contract-level _demo=False."""
    emitter = OvernightDeltaEmitter()

    def assemble_with_one_real(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "fx_overnight_moves": {
                "EURUSD": 0.004,
                "USDJPY": -0.002,
                "GBPUSD": 0.001,
            },
            # other buckets omitted → demo
        }

    with patch.object(emitter, "_assemble_context", side_effect=assemble_with_one_real):
        result = emitter.get_overnight_delta(account_id=1)

    fx = next(b for b in result.buckets if b.bucket == "FX")
    bonds = next(b for b in result.buckets if b.bucket == "BONDS")
    assert fx.demo is False
    assert bonds.demo is True
    assert result.demo is False


def test_emitter_overall_summary_always_populated():
    """overall_summary is deterministic — never empty."""
    emitter = OvernightDeltaEmitter()
    result = emitter.get_overnight_delta(account_id=1)
    assert result.overall_summary


def test_emitter_llm_enriched_summary_only_when_novelty_crossed():
    """LLM enrichment populated only when novelty.threshold_crossed AND not demo."""
    emitter = OvernightDeltaEmitter()

    def assemble_real(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "fx_overnight_moves": {"EURUSD": 0.005, "USDJPY": -0.002, "GBPUSD": 0.003},
            "bonds_overnight_moves": {"US10Y": 0.001, "DE10Y": 0.001, "JP10Y": 0.002},
            "commodities_overnight_moves": {"GC": 0.004, "CL": -0.005, "HG": 0.001},
            "crypto_overnight_moves": {"BTC": 0.020, "ETH": 0.015},
        }

    # Novelty NOT crossed
    fake_no_novelty = MagicMock(score=0.1, threshold_crossed=False, reason_codes=[])
    with patch.object(emitter, "_assemble_context", side_effect=assemble_real), \
         patch.object(emitter._novelty, "score", return_value=fake_no_novelty):
        result = emitter.get_overnight_delta(account_id=1)
    assert result.llm_enriched_summary is None
    assert result.demo is False  # sanity: real data → not demo

    # Novelty crossed → LLM populated
    fake_novelty = MagicMock(score=0.9, threshold_crossed=True, reason_codes=["VOL"])
    with patch.object(emitter, "_assemble_context", side_effect=assemble_real), \
         patch.object(emitter._novelty, "score", return_value=fake_novelty), \
         patch.object(emitter, "_call_llm", return_value="ENRICHED OVERVIEW"):
        result2 = emitter.get_overnight_delta(account_id=1)
    assert result2.llm_enriched_summary == "ENRICHED OVERVIEW"


def test_emitter_direction_up_when_all_symbols_positive():
    """All bucket symbols positive → direction=up."""
    emitter = OvernightDeltaEmitter()

    def assemble(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "fx_overnight_moves": {"EURUSD": 0.005, "USDJPY": 0.003, "GBPUSD": 0.004},
        }

    with patch.object(emitter, "_assemble_context", side_effect=assemble):
        result = emitter.get_overnight_delta(account_id=1)

    fx = next(b for b in result.buckets if b.bucket == "FX")
    assert fx.direction == "up"


def test_emitter_direction_mixed_when_split():
    emitter = OvernightDeltaEmitter()

    def assemble(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "fx_overnight_moves": {"EURUSD": 0.005, "USDJPY": -0.003, "GBPUSD": 0.001},
        }

    with patch.object(emitter, "_assemble_context", side_effect=assemble):
        result = emitter.get_overnight_delta(account_id=1)

    fx = next(b for b in result.buckets if b.bucket == "FX")
    assert fx.direction == "mixed"


def test_emitter_magnitude_extreme_when_large_move():
    emitter = OvernightDeltaEmitter()

    def assemble(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "crypto_overnight_moves": {"BTC": 0.05, "ETH": 0.06},  # 5-6% > 2.5% → extreme
        }

    with patch.object(emitter, "_assemble_context", side_effect=assemble):
        result = emitter.get_overnight_delta(account_id=1)

    crypto = next(b for b in result.buckets if b.bucket == "CRYPTO")
    assert crypto.magnitude_label == "extreme"


def test_emitter_magnitude_small_for_tiny_move():
    emitter = OvernightDeltaEmitter()

    def assemble(account_id):
        emitter._health.report("vm100", available=True)
        emitter._health.report("vm102", available=True)
        return {
            "fx_overnight_moves": {"EURUSD": 0.001, "USDJPY": 0.002, "GBPUSD": 0.001},
        }

    with patch.object(emitter, "_assemble_context", side_effect=assemble):
        result = emitter.get_overnight_delta(account_id=1)

    fx = next(b for b in result.buckets if b.bucket == "FX")
    assert fx.magnitude_label == "small"


# ── 3. Capability YAML ──────────────────────────────────────────────────────


_VM107_ROOT = Path(__file__).resolve().parents[2]
_YAML_PATH = _VM107_ROOT / "registry" / "tool" / "vm107.overnight_delta.yaml"


def test_overnight_delta_capability_yaml_exists():
    assert _YAML_PATH.exists(), f"Missing capability YAML at {_YAML_PATH}"


def test_overnight_delta_capability_yaml_has_required_keys():
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    assert data["id"] == "vm107.overnight_delta"
    assert data["type"] == "tool"
    assert data.get("description")
    assert data.get("vm") == "vm107"


# ── 4. VM100 client tests ───────────────────────────────────────────────────


class TestVM107OvernightDeltaClient:

    def test_client_fail_fast_on_missing_env(self, monkeypatch):
        import sys
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.delenv("VM107_BASE_URL", raising=False)
        from mission_control.clients.vm107_overnight_delta_client import (
            VM107OvernightDeltaClient,
        )
        with pytest.raises(KeyError):
            VM107OvernightDeltaClient()

    @pytest.mark.asyncio
    async def test_client_get_overnight_delta_returns_contract(self, monkeypatch):
        import sys
        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.setenv("VM107_API_TOKEN", "test-token")

        from mission_control.clients.vm107_overnight_delta_client import (
            VM107OvernightDeltaClient,
        )

        wire = {
            "delta_id": "d-1",
            "account_id": 7,
            "generated_at": "2026-05-25T06:00:00Z",
            "buckets": [
                {
                    "bucket": "FX",
                    "headline": "Dollar firms vs majors",
                    "notable_symbols": ["EURUSD", "USDJPY"],
                    "direction": "down",
                    "magnitude_label": "moderate",
                    "confidence": 0.85,
                    "_demo": False,
                },
                {
                    "bucket": "BONDS",
                    "headline": "Yields drift higher",
                    "notable_symbols": ["US10Y"],
                    "direction": "up",
                    "magnitude_label": "small",
                    "confidence": 0.80,
                    "_demo": False,
                },
                {
                    "bucket": "COMMODITIES",
                    "headline": "Gold steady, crude soft",
                    "notable_symbols": ["GC", "CL"],
                    "direction": "mixed",
                    "magnitude_label": "small",
                    "confidence": 0.75,
                    "_demo": False,
                },
                {
                    "bucket": "CRYPTO",
                    "headline": "BTC pares overnight gains",
                    "notable_symbols": ["BTC"],
                    "direction": "down",
                    "magnitude_label": "small",
                    "confidence": 0.70,
                    "_demo": False,
                },
            ],
            "overall_summary": "Quiet overnight session.",
            "llm_enriched_summary": None,
            "confidence_score": 0.85,
            "confidence_tier": "FULL",
            "missing_sources": [],
            "_demo": False,
        }

        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value=wire)
        fake_response.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(return_value=fake_response)

        with patch("httpx.AsyncClient", return_value=fake_client):
            client = VM107OvernightDeltaClient()
            result = await client.get_overnight_delta(account_id=7)

        assert result.delta_id == "d-1"
        assert result.account_id == 7
        assert len(result.buckets) == 4
        assert [b.bucket for b in result.buckets] == ["FX", "BONDS", "COMMODITIES", "CRYPTO"]


# ── 5. Golden round-trip ───────────────────────────────────────────────────


_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "golden"
    / "overnight_delta"
    / "sample.json"
)


def test_overnight_delta_golden_round_trip():
    raw = _FIXTURE_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    contract = OvernightDeltaContract.model_validate(data)
    rebuilt = contract.model_dump(mode="json", by_alias=True)
    assert rebuilt == data, "Golden fixture drift — update sample.json + downstream consumers."
