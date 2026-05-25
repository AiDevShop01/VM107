"""Phase 67 Plan 07 — ReflectionPromptEmitter + golden round-trip + YAML + client.

Covers the top-level facade (Task 3):

  * ReflectionPromptEmitter.get_reflection_prompts() → ReflectionPromptSetContract
  * Shared NoveltyEngine + VM100 chokepoint client injection
  * Capability YAML at VM107/registry/tool/vm107.reflection_prompt.yaml
  * VM100 client wrapper at VM100/backend/mission_control/clients/
    vm107_reflection_prompt_client.py
  * Golden round-trip fixture documents the expected wire shape
  * Persist + publish wraps SnapshotInvalidationPublisher in
    transaction.atomic() with the locked topic
    'mission_control.close.journal_prompts'
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from emitters.contracts.reflection_prompt import (
    EvidenceChainItem,
    ReflectionPromptContract,
    ReflectionPromptSetContract,
)
from emitters.novelty_engine import NoveltyEngine
from emitters.reflection_prompt_emitter import ReflectionPromptEmitter


pytestmark = pytest.mark.phase_67


# ── 1. Golden fixture round-trip ───────────────────────────────────────────


_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "golden"
    / "reflection_prompt"
    / "sample_set.json"
)


def test_golden_fixture_exists():
    """Golden fixture file must exist."""
    assert _FIXTURE_PATH.exists(), f"Missing fixture at {_FIXTURE_PATH}"


def test_golden_fixture_round_trips():
    """sample_set.json → contract → serializes back byte-stable (semantic)."""
    raw = _FIXTURE_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    contract = ReflectionPromptSetContract.model_validate(data)
    rebuilt = contract.model_dump(mode="json")
    assert rebuilt == data, (
        "Golden fixture round-trip mismatch — contract shape changed. "
        "Update sample_set.json AND notify Plan 10 / Plan 12 owners."
    )


def test_golden_fixture_has_required_top_keys():
    """Top-level set contract carries id + account + selected + rejected + coherence."""
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    required = {
        "set_id",
        "account_id",
        "generated_at",
        "selected_prompts",
        "rejected_candidates",
        "reflection_set_coherence_score",
        "dominant_session_theme",
    }
    missing = required - set(data.keys())
    assert not missing, f"Golden fixture missing top-level fields: {missing}"


def test_golden_fixture_includes_rejected_candidates():
    """REJECTED candidates persisted — Phase 62 tuning gold."""
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["rejected_candidates"], list)
    assert len(data["rejected_candidates"]) >= 1
    for rej in data["rejected_candidates"]:
        assert rej["selected"] is False
        assert rej["rejection_reason"]


def test_golden_fixture_evidence_chain_structured():
    """Each prompt's evidence_chain has structured {kind, ref, weight} items."""
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    for p in data["selected_prompts"]:
        for item in p["evidence_chain"]:
            assert "kind" in item
            assert "ref" in item
            assert "weight" in item
            assert 0.0 <= item["weight"] <= 1.0


def test_golden_fixture_both_base_and_llm_enriched_when_crossed():
    """Sample includes at least one prompt with both base + llm_enriched populated."""
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    enriched = [
        p for p in data["selected_prompts"]
        if p.get("llm_enriched_prompt") is not None
    ]
    # Golden documents the expected case — at least one enriched in the set
    assert len(enriched) >= 1
    for p in enriched:
        assert p["base_prompt"]  # base ALWAYS populated regardless


# ── 2. Emitter facade ──────────────────────────────────────────────────────


def test_emitter_uses_shared_novelty_engine_by_default():
    """When no novelty_engine is injected, falls back to shared singleton (Phase 66 lock)."""
    e1 = ReflectionPromptEmitter()
    e2 = ReflectionPromptEmitter()
    assert e1._novelty is e2._novelty  # same shared instance


def test_emitter_uses_injected_novelty_engine():
    """Constructor takes an explicit NoveltyEngine."""
    local = NoveltyEngine()
    e = ReflectionPromptEmitter(novelty_engine=local)
    assert e._novelty is local


def test_emitter_returns_set_contract():
    """get_reflection_prompts() returns ReflectionPromptSetContract."""
    fake_vm100 = MagicMock()
    fake_vm100.get_trade_outcomes_for_session = MagicMock(
        return_value=[
            {
                "trade_id": "t-1",
                "symbol": "EURUSD",
                "entry_at": "2026-05-25T09:15:00Z",
                "exit_at": "2026-05-25T10:30:00Z",
                "pnl_r": -1.2,
                "regime": "RANGE",
                "behavioral_tags": ["premature_entry"],
            }
        ]
    )
    fake_vm100.get_mentor_narrative_for_trade = MagicMock(
        return_value={
            "discipline_flags": ["premature_entry", "size_violation"],
            "narrative_summary": "Entered before M5 BOS during compression.",
            "confidence": 0.78,
        }
    )
    fake_vm100.get_session_patterns = MagicMock(
        return_value=[
            {
                "pattern_id": "premature_entry_cluster",
                "pattern_name": "premature_entry_cluster",
                "supporting_trade_ids": ["t-1"],
                "severity": 0.7,
            }
        ]
    )
    fake_vm100.get_behavioral_evolution = MagicMock(
        return_value={
            "evolution_trend": "worsening",
            "behavioral_trajectory": "discipline_drift_4w",
        }
    )
    fake_vm100.get_adaptive_recommendation = MagicMock(
        return_value={
            "recommendation": "Reduce session size by 25% on Mondays",
            "target_surface": "category_point_weight",
        }
    )

    emitter = ReflectionPromptEmitter(vm100_client=fake_vm100)
    result = emitter.get_reflection_prompts(
        account_id=42, session_date=date(2026, 5, 25)
    )

    assert isinstance(result, ReflectionPromptSetContract)
    assert result.account_id == 42
    assert 0 < len(result.selected_prompts) <= 4


def test_emitter_returns_empty_set_when_no_observations():
    """No trades in session → empty selected + rejected lists (no eligibility)."""
    fake_vm100 = MagicMock()
    fake_vm100.get_trade_outcomes_for_session = MagicMock(return_value=[])
    fake_vm100.get_mentor_narrative_for_trade = MagicMock(return_value={})
    fake_vm100.get_session_patterns = MagicMock(return_value=[])
    fake_vm100.get_behavioral_evolution = MagicMock(return_value={})
    fake_vm100.get_adaptive_recommendation = MagicMock(return_value={})

    emitter = ReflectionPromptEmitter(vm100_client=fake_vm100)
    result = emitter.get_reflection_prompts(
        account_id=42, session_date=date(2026, 5, 25)
    )
    assert result.selected_prompts == []
    assert result.rejected_candidates == []


def test_persist_and_publish_uses_close_topic():
    """persist_and_publish publishes on mission_control.close.journal_prompts."""
    # Mock the Django + publisher chain
    import sys
    import types

    fake_publisher_instance = MagicMock()
    fake_publisher_module = types.ModuleType(
        "mission_control.services.snapshot_invalidation_publisher"
    )
    fake_publisher_module.SnapshotInvalidationPublisher = MagicMock(  # type: ignore[attr-defined]
        return_value=fake_publisher_instance
    )
    fake_mc_services = types.ModuleType("mission_control.services")
    fake_mc_services.snapshot_invalidation_publisher = fake_publisher_module  # type: ignore[attr-defined]
    fake_mc_pkg = types.ModuleType("mission_control")
    fake_mc_pkg.services = fake_mc_services  # type: ignore[attr-defined]

    saved = {}
    for name, mod in [
        ("mission_control", fake_mc_pkg),
        ("mission_control.services", fake_mc_services),
        (
            "mission_control.services.snapshot_invalidation_publisher",
            fake_publisher_module,
        ),
    ]:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod

    # Fake django.db.transaction.atomic context manager
    fake_django = types.ModuleType("django")
    fake_django_db = types.ModuleType("django.db")

    class _Atomic:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    fake_transaction = MagicMock()
    fake_transaction.atomic = MagicMock(return_value=_Atomic())
    fake_django_db.transaction = fake_transaction  # type: ignore[attr-defined]
    fake_django.db = fake_django_db  # type: ignore[attr-defined]
    saved["django"] = sys.modules.get("django")
    saved["django.db"] = sys.modules.get("django.db")
    sys.modules["django"] = fake_django
    sys.modules["django.db"] = fake_django_db

    try:
        emitter = ReflectionPromptEmitter()
        # Build a minimal contract
        set_contract = ReflectionPromptSetContract(
            set_id="rps-test-1",
            account_id=42,
            generated_at="2026-05-25T18:00:00Z",
            selected_prompts=[],
            rejected_candidates=[],
            reflection_set_coherence_score=1.0,
            dominant_session_theme=None,
        )
        emitter.persist_and_publish(set_contract)

        fake_publisher_instance.publish_after_commit.assert_called_once()
        call_kwargs = fake_publisher_instance.publish_after_commit.call_args.kwargs
        assert call_kwargs["topic"] == "mission_control.close.journal_prompts"
        assert call_kwargs["snapshot_id"] == "rps-test-1"
        assert call_kwargs["account_id"] == 42
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


# ── 3. Capability YAML ─────────────────────────────────────────────────────


_VM107_ROOT = Path(__file__).resolve().parents[2]
_YAML_PATH = _VM107_ROOT / "registry" / "tool" / "vm107.reflection_prompt.yaml"


def test_reflection_prompt_capability_yaml_exists():
    """Phase 47.6 lock — capability YAML must be registered."""
    assert _YAML_PATH.exists(), f"Missing capability YAML at {_YAML_PATH}"


def test_reflection_prompt_capability_yaml_has_required_keys():
    """YAML carries id / type / description / vm / dependencies."""
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    assert data["id"] == "vm107.reflection_prompt"
    assert data["type"] == "tool"  # fall back to 'tool' (emitter not in 16-type taxonomy)
    assert data.get("description")
    assert data.get("vm") == "vm107"
    assert data.get("dependencies")
    ws_topics = data.get("ws_topics") or []
    assert "mission_control.close.journal_prompts" in ws_topics


# ── 4. VM100 client wrapper ────────────────────────────────────────────────


class TestVM107ReflectionPromptClient:
    """VM100 chokepoint wrapper tests — env fail-fast + HTTP wiring."""

    def _inject_vm100(self):
        import sys

        vm100_backend = str(
            Path(__file__).resolve().parents[3] / "VM100" / "backend"
        )
        if vm100_backend not in sys.path:
            sys.path.insert(0, vm100_backend)

    def test_client_fail_fast_on_missing_base_url(self, monkeypatch):
        self._inject_vm100()
        monkeypatch.delenv("VM107_BASE_URL", raising=False)
        from mission_control.clients.vm107_reflection_prompt_client import (
            VM107ReflectionPromptClient,
        )
        with pytest.raises(KeyError):
            VM107ReflectionPromptClient()

    def test_client_fail_fast_on_missing_token(self, monkeypatch):
        self._inject_vm100()
        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.delenv("VM107_API_TOKEN", raising=False)
        from mission_control.clients.vm107_reflection_prompt_client import (
            VM107ReflectionPromptClient,
        )
        with pytest.raises(KeyError):
            VM107ReflectionPromptClient()

    @pytest.mark.asyncio
    async def test_client_get_reflection_prompts_returns_contract(self, monkeypatch):
        self._inject_vm100()
        monkeypatch.setenv("VM107_BASE_URL", "http://vm107:50080")
        monkeypatch.setenv("VM107_API_TOKEN", "test-token")

        from mission_control.clients.vm107_reflection_prompt_client import (
            VM107ReflectionPromptClient,
            ReflectionPromptSetContract as ClientSetContract,
        )

        wire = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        fake_response = MagicMock()
        fake_response.json = MagicMock(return_value=wire)
        fake_response.raise_for_status = MagicMock()

        fake_client = MagicMock()
        fake_client.__aenter__ = MagicMock()
        fake_client.__aexit__ = MagicMock()

        from unittest.mock import AsyncMock, patch as mpatch

        async def _aenter(*args):
            return fake_client

        async def _aexit(*args):
            return False

        fake_client.__aenter__ = _aenter
        fake_client.__aexit__ = _aexit
        fake_client.get = AsyncMock(return_value=fake_response)

        client = VM107ReflectionPromptClient()
        with mpatch(
            "mission_control.clients.vm107_reflection_prompt_client.httpx.AsyncClient",
            return_value=fake_client,
        ):
            result = await client.get_reflection_prompts(
                account_id=42, session_date="2026-05-25"
            )
        assert isinstance(result, ClientSetContract)
        assert result.account_id == wire["account_id"]
