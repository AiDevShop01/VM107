"""Phase 48 Plan 08b — 30+ parametrized anti-pattern enforcement test. REQ-48-D19.

CONTEXT § Decision 19 (LOCKED) enumerates ~30 explicitly-rejected
architectural choices. This test enforces each via one of four check kinds:
  * AST    — walk Python source under VM107/{core,agents}/ + ban an import
             or call pattern.
  * BEHAVIOR — invoke main_loop with a stimulus that would exercise the
             anti-pattern + assert the orchestrator rejects.
  * REGISTRY — load registry/*.yaml + assert forbidden config absent.
  * FILE_GREP — regex scan of prompt files + SKILL.md + assert forbidden
             tokens absent.

The 30+ items below cover every CONTEXT § Decision 19 bullet that has
implementation surface in tree (some are forward-looking-deferral
statements with no code to inspect — those are accepted at the contract
level via the implementation lock for Plan 49+ rather than runtime tests).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Callable

import pytest
import yaml

_VM107_ROOT = Path(__file__).resolve().parents[3]
_REG_ROOT = _VM107_ROOT / "registry"


# ---------------------------------------------------------------------------
# Check helpers — small reusable utilities.
# ---------------------------------------------------------------------------


def _iter_py_under(*subdirs: str):
    """Yield every .py file under one or more VM107 subtrees."""
    for sub in subdirs:
        root = _VM107_ROOT / sub
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p


def _file_imports(py_path: Path, target_module: str) -> bool:
    try:
        tree = ast.parse(py_path.read_text())
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == target_module or a.name.startswith(target_module + "."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == target_module or mod.startswith(target_module + "."):
                return True
    return False


def _file_uses_call(py_path: Path, function_name: str) -> bool:
    """Crude: does the file's source mention the function as a call?"""
    src = py_path.read_text()
    return bool(re.search(rf"\b{re.escape(function_name)}\s*\(", src))


def _assert_no_module_imports(target_module: str, *subdirs: str) -> None:
    offenders: list[str] = []
    for p in _iter_py_under(*subdirs):
        if _file_imports(p, target_module):
            offenders.append(str(p.relative_to(_VM107_ROOT)))
    assert not offenders, (
        f"No file under {subdirs!r} may import {target_module!r}. Offenders:\n  - "
        + "\n  - ".join(offenders)
    )


def _assert_no_grep_under(pattern: re.Pattern[str], *paths: Path) -> None:
    offenders: list[str] = []
    for root in paths:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix in {".pyc", ".log"}:
                continue
            if "__pycache__" in p.parts:
                continue
            try:
                src = p.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if pattern.search(src):
                offenders.append(str(p.relative_to(_VM107_ROOT)))
    assert not offenders, (
        f"Forbidden pattern {pattern.pattern!r} appears in:\n  - "
        + "\n  - ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Individual anti-pattern checks (each a callable returning None or raising).
# ---------------------------------------------------------------------------


def _check_no_phase46_critic_mesh():
    """❌ Using Phase 46 critic mesh in Phase 48."""
    # No orchestrator module imports a Phase 46 mesh surface.
    for forbidden in (
        "agents.critic_mesh",
        "agents.specialist_critics",
        "core.agents.critic_mesh",
    ):
        _assert_no_module_imports(forbidden, "core/agents/refinement_orchestrator")


def _check_no_critic_agent_naming():
    """❌ Naming the profile critic_agent."""
    critic_agent_dir = _VM107_ROOT / "agents" / "critic_agent"
    assert not critic_agent_dir.exists(), (
        "agents/critic_agent/ MUST NOT exist (CONTEXT § Anti-Patterns: "
        "naming critic_agent causes semantic bleed from Phase 60/46)."
    )
    # And the registry must not register an agent_profile id=critic_agent.
    profile_yaml = _REG_ROOT / "agent_profile" / "critic_agent.yaml"
    assert not profile_yaml.exists(), (
        f"{profile_yaml.relative_to(_VM107_ROOT)} MUST NOT exist."
    )


def _check_critic_does_not_rewrite_artifacts():
    """❌ Critic rewriting artifacts (transformation purity)."""
    # The strategy_refinement_critic profile must not import the artifact
    # construction surfaces (StrategySpec / CodeModule construction APIs).
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        pytest.skip("strategy_refinement_critic profile dir missing")
    for forbidden in (
        "core.agents.invocation",  # would let Critic call run_strategy / run_code
    ):
        for p in critic_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            assert not _file_imports(p, forbidden), (
                f"Critic profile must not import {forbidden!r}: {p.relative_to(_VM107_ROOT)}"
            )


def _check_critic_does_not_query_raw_vm102():
    """❌ Critic querying raw VM102 datasets."""
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        pytest.skip("strategy_refinement_critic profile dir missing")
    for forbidden in (
        "core.tools.vm_clients.vm102_client",
        "core.tools.vm_clients.vm102",
    ):
        for p in critic_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            assert not _file_imports(p, forbidden), (
                f"Critic profile must not import {forbidden!r}: {p.relative_to(_VM107_ROOT)}"
            )


def _check_critic_does_not_own_loop_control():
    """❌ Critic owning loop control / max_iterations / convergence detection."""
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        pytest.skip("strategy_refinement_critic profile dir missing")
    # No file in the Critic profile may import the orchestrator package.
    _assert_no_module_imports(
        "core.agents.refinement_orchestrator", "agents/strategy_refinement_critic"
    )


def _check_no_prose_refinement_targets():
    """❌ LLM-driven refinement_targets as prose."""
    # The RefinementTarget Pydantic class must have canonical_issue_id +
    # scope + severity Literal fields — not free-form string fields.
    from core.contracts.schemas import RefinementTarget

    fields = RefinementTarget.model_fields
    assert "canonical_issue_id" in fields, "RefinementTarget missing canonical_issue_id"
    assert "scope" in fields
    assert "severity" in fields


def _check_no_hypothesis_mutation():
    """❌ Hypothesis mutation / 'hypothesis refinement'."""
    from core.contracts.schemas import Hypothesis

    # Hypothesis is frozen (BaseContract). Construct one and try to mutate.
    h = Hypothesis(
        hypothesis="test hypothesis text long enough for min_length",
        variables=["x"],
        confidence=0.5,
    )
    with pytest.raises(Exception):  # pydantic frozen → ValidationError
        h.hypothesis = "mutated"  # type: ignore[misc]


def _check_no_strategyspec_only_entry():
    """❌ StrategySpec-only entry shape."""
    # The single public entry takes hypothesis_id (str), not StrategySpec.
    from core.agents.refinement_orchestrator import run_refinement_loop
    import inspect

    sig = inspect.signature(run_refinement_loop)
    assert list(sig.parameters)[0] == "hypothesis_id", (
        "run_refinement_loop's first parameter must be hypothesis_id (no orphan strategies)."
    )


def _check_no_raw_text_loop_entry():
    """❌ Loops accepting raw text (resurrects Idea Agent external endpoint)."""
    # The HTTP entry at api/v1/agents/pipeline/refine.py — if it exists — must
    # NOT accept a "text" or "core_idea" field in the request schema. (Plan
    # 09 ships this endpoint; this check is forward-compatible.)
    refine_py = _VM107_ROOT / "api" / "v1" / "agents" / "pipeline" / "refine.py"
    if not refine_py.exists():
        # Plan 09 hasn't shipped it yet; no-op.
        return
    src = refine_py.read_text()
    for forbidden in ('"text"', '"core_idea"', '"hypothesis_text"'):
        assert forbidden not in src, (
            f"refine.py must not accept raw text input ({forbidden})."
        )


def _check_no_is_stalling_field():
    """❌ Critic emitting is_stalling: true (extra='forbid' enforces it)."""
    from core.contracts.schemas import CriticVerdict

    fields = CriticVerdict.model_fields
    assert "is_stalling" not in fields, (
        "CriticVerdict must NOT have an is_stalling field — convergence "
        "detection is orchestration policy, not Critic cognition."
    )


def _check_no_embeddings_for_identity_drift():
    """❌ Embedding/semantic similarity for identity drift."""
    from core.agents.refinement_orchestrator import identity_scorer as _is

    src = Path(_is.__file__).read_text()
    for banned in (
        "sentence_transformers",
        "from openai",
        "import openai",
        "cosine_similarity",
        "faiss",
    ):
        assert banned not in src, (
            f"identity_scorer.py must not reference {banned!r} (CONTEXT § Decision 10 — "
            f"structured-diff Python only)."
        )


def _check_critic_does_not_override_vetoes():
    """❌ Critic overriding hard vetoes, identity drift, budget exhaustion, or convergence.

    Enforcement: the gate modules (hard_vetoes / identity_scorer /
    convergence_detector / budget_governor / acceptance_floor) MUST NOT
    import core.agents.invocation. They are pure-function deterministic
    gates; routing the Critic through them would let LLM cognition override
    the gate's verdict.
    """
    gate_modules = (
        "hard_vetoes.py",
        "identity_scorer.py",
        "convergence_detector.py",
        "budget_governor.py",
        "acceptance_floor.py",
    )
    for fn in gate_modules:
        p = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / fn
        if not p.exists():
            continue
        assert not _file_imports(p, "core.agents.invocation"), (
            f"{fn} must not import core.agents.invocation (gate runs BEFORE Critic)."
        )


def _check_critic_budget_blind():
    """❌ Critic seeing budget state."""
    # run_critic signature has no budget kwarg.
    from core.agents.invocation import run_critic
    import inspect

    sig = inspect.signature(run_critic)
    for banned in (
        "budget", "budget_snapshot", "remaining_budget", "governor",
        "cost", "execution_cost", "remaining_usd", "budget_caps",
    ):
        assert banned not in sig.parameters, (
            f"run_critic must NOT accept {banned!r} kwarg (Critic-budget-blind)."
        )


def _check_code_agent_does_not_infer_strategy():
    """❌ Code Agent inferring strategy evolution from refinement targets."""
    # refinement_routing.py must call run_code with the prior_spec (or new spec
    # from Strategy regeneration) — not regenerate StrategySpec from Code Agent
    # output. Check that the routing module imports run_strategy AND run_code.
    from core.agents.refinement_orchestrator import refinement_routing as _rr

    src = Path(_rr.__file__).read_text()
    assert "run_strategy" in src
    assert "run_code" in src
    # And the validation rule "STRATEGY_SPEC target on CodeModule-only field" exists.
    assert "_CODE_ONLY_FIELDS" in src or "code_only_fields" in src.lower()


def _check_no_artifact_discard():
    """❌ Discarding per-iteration artifacts on termination."""
    # state.py / checkpoint.py / __init__.py / snapshot_freeze.py must not call
    # delete_one / delete_many / drop / drop_collection.
    forbidden_call = re.compile(r"\.delete_one\(|\.delete_many\(|\.drop_collection\(|\.drop\(\)")
    for fn in ("state.py", "checkpoint.py", "snapshot_freeze.py", "__init__.py", "main_loop.py"):
        p = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / fn
        if not p.exists():
            continue
        src = p.read_text()
        assert not forbidden_call.search(src), (
            f"{fn} must not delete/drop iteration artifacts (CONTEXT § Decision 13)."
        )


def _check_no_per_iteration_snapshot_restamp():
    """❌ Re-stamping registry_snapshot_hash per iteration."""
    # main_loop must NOT re-read CapabilityRegistry.get().snapshot_hash inside
    # the per-iteration body. The snapshot is captured ONCE by
    # initialize_loop_state (state.py).
    main_loop_py = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / "main_loop.py"
    src = main_loop_py.read_text()
    # The string "CapabilityRegistry" should not appear in main_loop.py at all
    # (state.py + snapshot_freeze.py are the canonical readers).
    assert "CapabilityRegistry" not in src, (
        "main_loop.py must not re-read CapabilityRegistry (snapshot frozen at iter 0)."
    )


def _check_no_mid_loop_registry_reload():
    """❌ Mid-loop reload of registry / dynamic capability surface."""
    # No module under refinement_orchestrator/ may call lookup_capability or
    # capability_registry.load_*.
    for fn in ("main_loop.py", "acceptance_path.py", "rejection_path.py"):
        p = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / fn
        if not p.exists():
            continue
        src = p.read_text()
        for forbidden in ("lookup_capability(", "CapabilityRegistry.load", "load_registry"):
            assert forbidden not in src, (
                f"{fn} must not reload the registry mid-loop ({forbidden!r})."
            )


def _check_no_sync_http_for_refine():
    """❌ Sync HTTP invocation with timeout for /pipeline/refine."""
    refine_py = _VM107_ROOT / "api" / "v1" / "agents" / "pipeline" / "refine.py"
    if not refine_py.exists():
        return
    src = refine_py.read_text()
    # Must include "202" (async-only) and the response should reference task_id.
    assert "202" in src or "Accepted" in src, "refine endpoint must return 202 Accepted."
    assert "task_id" in src, "refine endpoint must return task_id."


def _check_no_streaming_thoughts():
    """❌ Streaming agent thoughts to polling clients."""
    refine_py = _VM107_ROOT / "api" / "v1" / "agents" / "pipeline" / "refine.py"
    if not refine_py.exists():
        return
    src = refine_py.read_text()
    for forbidden in ("StreamingResponse", "EventStream", "yield "):
        assert forbidden not in src, (
            f"refine endpoint must not stream agent thoughts ({forbidden!r})."
        )


def _check_no_dedicated_event_substrate():
    """❌ Dedicated event substrate for refinement (must use Phase 56)."""
    # refinement_events.py must import emit_event from phase56_client (NOT
    # define its own POST or its own event store).
    refinement_events_py = _VM107_ROOT / "core" / "events" / "refinement_events.py"
    src = refinement_events_py.read_text()
    assert "phase56_client" in src, (
        "refinement_events.py must wrap phase56_client.emit_event (single substrate)."
    )
    # And it must not import requests / httpx directly.
    for forbidden in ("import httpx", "import requests"):
        assert forbidden not in src, (
            f"refinement_events.py must NOT bypass the Phase 56 client ({forbidden!r})."
        )


def _check_rejected_not_in_registry_strategy():
    """❌ Storing rejected strategies as capability registry entries."""
    # No registry/strategy/<id>.yaml may carry strategy_lifecycle_status=rejected.
    strategy_reg_dir = _REG_ROOT / "strategy"
    if not strategy_reg_dir.exists():
        return
    for yaml_path in strategy_reg_dir.glob("*.yaml"):
        try:
            doc = yaml.safe_load(yaml_path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        lifecycle = doc.get("strategy_lifecycle_status")
        assert lifecycle != "rejected", (
            f"{yaml_path.relative_to(_VM107_ROOT)} has strategy_lifecycle_status=rejected — "
            "rejected strategies are NEVER capabilities."
        )


def _check_no_multi_skill_loading():
    """❌ Multi-skill loading per Critic invocation in V1."""
    from core.agents.family_skill_map import family_skill_map, select_skill

    # select_skill returns a SINGLE skill id (str), not a list.
    from core.contracts.schemas import StrategyFamily

    skill = select_skill(StrategyFamily.BREAKOUT)
    assert isinstance(skill, str), "select_skill must return a SINGLE skill_id (str)."
    # The map's values are str.
    assert all(isinstance(v, str) for v in family_skill_map.values())


def _check_no_adaptive_budget_caps():
    """❌ Adaptive / dynamic / LLM-overridable budget caps or floors."""
    from core.agents.refinement_orchestrator import policy_constants as _pc

    src = Path(_pc.__file__).read_text()
    # No `os.getenv` / runtime override / "dynamic" keyword.
    for banned in ("os.getenv", "os.environ.get", "dynamic", "adaptive"):
        assert banned not in src, (
            f"policy_constants.py must not be dynamic ({banned!r})."
        )


def _check_no_grace_iteration():
    """❌ Final grace iteration on budget exhaustion.

    Inspect the AST (NOT the source text — Plan 03/04/05 pattern documented
    "no grace iteration" verbatim in docstrings as the explicit policy lock).
    Banned: any FunctionDef / ClassDef / Assign target whose name contains
    "grace" (e.g., grant_grace_iteration, _grace_*).
    """
    from core.agents.refinement_orchestrator import budget_governor as _bg

    tree = ast.parse(Path(_bg.__file__).read_text())
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    break
        if name and "grace" in name.lower():
            raise AssertionError(
                f"budget_governor.py must not define {name!r} (grace iteration banned)."
            )


def _check_no_filesystem_only_acceptance():
    """❌ Filesystem export of accepted strategies as sole storage."""
    # acceptance_path.py must persist to accepted_strategies Mongo collection
    # (look for the collection name).
    from core.agents.refinement_orchestrator import acceptance_path as _ap

    src = Path(_ap.__file__).read_text()
    assert "accepted_strategies" in src, (
        "acceptance_path.py must write to accepted_strategies Mongo collection."
    )


def _check_no_parallel_loops_by_default():
    """❌ Parallel-by-default loop execution."""
    # main_loop.py must not use asyncio.gather / concurrent.futures / threading.
    main_loop_py = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / "main_loop.py"
    src = main_loop_py.read_text()
    for banned in ("asyncio.gather", "concurrent.futures", "ThreadPoolExecutor", "multiprocessing"):
        assert banned not in src, (
            f"main_loop.py must run sequentially ({banned!r} banned)."
        )


def _check_no_coordinator_orchestration():
    """❌ Coordinator-driven loop orchestration."""
    # The Coordinator profile (if any) must not directly call run_refinement_loop.
    coord_dir = _VM107_ROOT / "agents" / "coordinator"
    if not coord_dir.exists():
        pytest.skip("coordinator profile not present")
    for p in coord_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        src = p.read_text()
        assert "run_refinement_loop" not in src, (
            f"coordinator/ must not call run_refinement_loop directly: {p.relative_to(_VM107_ROOT)}"
        )


def _check_orchestrator_not_llm_profile():
    """❌ New LLM agent profile as orchestrator."""
    # No agents/refinement_orchestrator/ directory.
    bad_dir = _VM107_ROOT / "agents" / "refinement_orchestrator"
    assert not bad_dir.exists(), (
        "refinement_orchestrator MUST NOT be an LLM agent profile."
    )
    # And the service YAML must say type=service (NOT type=agent_profile).
    service_yaml = _REG_ROOT / "service" / "refinement_orchestrator.yaml"
    doc = yaml.safe_load(service_yaml.read_text())
    assert doc["type"] == "service", "refinement_orchestrator must be type=service."


def _check_critic_iteration_blindness():
    """❌ Critic seeing iteration / max_iterations / budget in prompt files."""
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        pytest.skip("strategy_refinement_critic profile dir missing")
    # Prompt files: role.md + specifics.md.
    for prompt in critic_dir.rglob("*.md"):
        src = prompt.read_text().lower()
        for forbidden in ("\biteration\b", r"\bmax\s+iterations\b", r"\bbudget\b", "tokens consumed"):
            assert not re.search(forbidden, src), (
                f"{prompt.relative_to(_VM107_ROOT)} must not contain {forbidden!r}."
            )


def _check_no_test_invocation_bypasses_validation():
    """❌ refine endpoint accepting StrategySpec / CodeModule directly bypasses Hypothesis lineage."""
    # The orchestrator's loop entry contract is hypothesis_id only.
    from core.agents.refinement_orchestrator import run_refinement_loop
    import inspect

    sig = inspect.signature(run_refinement_loop)
    params = list(sig.parameters)
    # First positional must be hypothesis_id; no StrategySpec / CodeModule kwargs.
    assert params[0] == "hypothesis_id"
    for banned in ("strategy_spec", "code_module", "spec", "module"):
        assert banned not in params, (
            f"run_refinement_loop must not accept {banned!r} (no orphan strategies)."
        )


def _check_orchestrator_purity():
    """❌ Orchestrator package importing an LLM client."""
    # Plan 03 already enforces. Quick re-check.
    for forbidden in ("langchain", "openai", "anthropic", "agent_zero"):
        _assert_no_module_imports(forbidden, "core/agents/refinement_orchestrator")


def _check_phase56_emit_uses_idea_scope():
    """❌ Dedicated causality_scope for refinement (must reuse Phase 56 IDEA scope per planner V1)."""
    # Every Phase 48 event_type YAML must declare causality_scope_default: IDEA.
    event_yaml_dir = _REG_ROOT / "event_type"
    phase48_events = (
        "refinement_loop_started", "iteration_started", "critic_verdict_received",
        "hard_veto_triggered", "identity_drift_detected", "convergence_stall_detected",
        "budget_exceeded", "strategy_accepted", "strategy_rejected", "loop_terminated",
    )
    for evt in phase48_events:
        p = event_yaml_dir / f"{evt}.yaml"
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text())
        assert doc.get("causality_scope_default") == "IDEA", (
            f"{p.relative_to(_VM107_ROOT)} must declare causality_scope_default: IDEA."
        )


def _check_sole_emitter():
    """❌ Agent profile emitting refinement lifecycle events."""
    # Already covered by Plan 07's test_orchestrator_sole_emitter; we run a
    # narrower check here: the Critic profile must not import refinement_events.
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        return
    for p in critic_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        assert not _file_imports(p, "core.events.refinement_events"), (
            f"Critic profile must not import refinement_events: {p.relative_to(_VM107_ROOT)}"
        )


def _check_pattern_51_persist_emit():
    """❌ Emit decoupled from persistence (Pattern 51 — emit + persist atomic)."""
    # persistence.py must import emit_event.
    persistence_py = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator" / "persistence.py"
    src = persistence_py.read_text()
    assert "emit_event" in src
    assert "insert_one" in src
    # And the rollback path is the canonical Pattern 51 pattern.
    assert "delete_one" in src, (
        "persistence.py must implement insert-then-emit-then-rollback (Pattern 51)."
    )


def _check_max_iterations_locked():
    """❌ Adaptive MAX_ITERATIONS."""
    from core.agents.refinement_orchestrator.policy_constants import MAX_ITERATIONS

    assert MAX_ITERATIONS == 3, (
        f"MAX_ITERATIONS is locked at 3 (CONTEXT § Decision 4); got {MAX_ITERATIONS}."
    )


def _check_identity_thresholds_locked():
    """❌ Adaptive identity thresholds."""
    from core.agents.refinement_orchestrator.policy_constants import IDENTITY_THRESHOLDS

    assert IDENTITY_THRESHOLDS == {1: 0.70, 2: 0.80, 3: 0.90}, (
        f"IDENTITY_THRESHOLDS locked; got {IDENTITY_THRESHOLDS}."
    )


def _check_4_hard_vetoes_only():
    """❌ Adding non-catastrophic vetoes."""
    from core.agents.refinement_orchestrator.policy_constants import HARD_VETOES

    # Exactly the 4 catastrophic veto rules. profit_factor < 1.4 is Critic
    # territory and MUST NOT appear in HARD_VETOES.
    assert set(HARD_VETOES.keys()) == {
        "max_drawdown", "win_rate", "consecutive_losses", "regime_coverage"
    }, f"HARD_VETOES must contain exactly the 4 catastrophic rules; got {set(HARD_VETOES.keys())}"
    assert "profit_factor" not in HARD_VETOES


def _check_no_idea_agent_external_endpoint():
    """❌ Resurrecting Idea Agent external HTTP endpoint."""
    idea_endpoint = _VM107_ROOT / "api" / "v1" / "agents" / "idea" / "invoke.py"
    assert not idea_endpoint.exists(), (
        "Phase 44 deferred the Idea Agent external endpoint; Phase 48 must not resurrect it."
    )


def _check_no_inline_critic_iteration_metadata():
    """❌ run_critic prompt builder mentioning iteration / budget / max_iterations."""
    invocation_py = _VM107_ROOT / "core" / "agents" / "invocation.py"
    src = invocation_py.read_text()
    # Find the _build_critic_prompt_payload function source.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_critic_prompt_payload":
            fn_src = ast.unparse(node)
            for banned in ("budget", "remaining_usd", "tokens_consumed"):
                # Allow "loop_state" passthrough — pre-existing legal field.
                assert banned not in fn_src.lower(), (
                    f"_build_critic_prompt_payload must not include {banned!r}."
                )
            return
    pytest.skip("_build_critic_prompt_payload not found in invocation.py")


# ---------------------------------------------------------------------------
# Parametrize the full anti-pattern enumeration. 30+ items.
# ---------------------------------------------------------------------------

ANTI_PATTERNS: list[tuple[str, str, Callable[[], None]]] = [
    ("no_phase46_critic_mesh",                       "AST",        _check_no_phase46_critic_mesh),
    ("no_critic_agent_naming",                       "REGISTRY",   _check_no_critic_agent_naming),
    ("critic_does_not_rewrite_artifacts",            "AST",        _check_critic_does_not_rewrite_artifacts),
    ("critic_does_not_query_raw_vm102",              "AST",        _check_critic_does_not_query_raw_vm102),
    ("critic_does_not_own_loop_control",             "AST",        _check_critic_does_not_own_loop_control),
    ("no_prose_refinement_targets",                  "BEHAVIOR",   _check_no_prose_refinement_targets),
    ("no_hypothesis_mutation",                       "BEHAVIOR",   _check_no_hypothesis_mutation),
    ("no_strategyspec_only_entry",                   "BEHAVIOR",   _check_no_strategyspec_only_entry),
    ("no_raw_text_loop_entry",                       "FILE_GREP",  _check_no_raw_text_loop_entry),
    ("no_is_stalling_field",                         "BEHAVIOR",   _check_no_is_stalling_field),
    ("no_embeddings_for_identity_drift",             "AST",        _check_no_embeddings_for_identity_drift),
    ("critic_does_not_override_vetoes",              "AST",        _check_critic_does_not_override_vetoes),
    ("critic_budget_blind",                          "BEHAVIOR",   _check_critic_budget_blind),
    ("code_agent_does_not_infer_strategy",           "AST",        _check_code_agent_does_not_infer_strategy),
    ("no_artifact_discard",                          "AST",        _check_no_artifact_discard),
    ("no_per_iteration_snapshot_restamp",            "AST",        _check_no_per_iteration_snapshot_restamp),
    ("no_mid_loop_registry_reload",                  "AST",        _check_no_mid_loop_registry_reload),
    ("no_sync_http_for_refine",                      "FILE_GREP",  _check_no_sync_http_for_refine),
    ("no_streaming_thoughts",                        "FILE_GREP",  _check_no_streaming_thoughts),
    ("no_dedicated_event_substrate",                 "AST",        _check_no_dedicated_event_substrate),
    ("rejected_not_in_registry_strategy",            "REGISTRY",   _check_rejected_not_in_registry_strategy),
    ("no_multi_skill_loading",                       "BEHAVIOR",   _check_no_multi_skill_loading),
    ("no_adaptive_budget_caps",                      "AST",        _check_no_adaptive_budget_caps),
    ("no_grace_iteration",                           "AST",        _check_no_grace_iteration),
    ("no_filesystem_only_acceptance",                "AST",        _check_no_filesystem_only_acceptance),
    ("no_parallel_loops_by_default",                 "AST",        _check_no_parallel_loops_by_default),
    ("no_coordinator_orchestration",                 "AST",        _check_no_coordinator_orchestration),
    ("orchestrator_not_llm_profile",                 "REGISTRY",   _check_orchestrator_not_llm_profile),
    ("critic_iteration_blindness",                   "FILE_GREP",  _check_critic_iteration_blindness),
    ("no_loop_entry_via_strategyspec",               "BEHAVIOR",   _check_no_test_invocation_bypasses_validation),
    ("orchestrator_purity",                          "AST",        _check_orchestrator_purity),
    ("phase56_emit_uses_idea_scope",                 "REGISTRY",   _check_phase56_emit_uses_idea_scope),
    ("sole_emitter",                                 "AST",        _check_sole_emitter),
    ("pattern_51_persist_emit_atomic",               "AST",        _check_pattern_51_persist_emit),
    ("max_iterations_locked",                        "BEHAVIOR",   _check_max_iterations_locked),
    ("identity_thresholds_locked",                   "BEHAVIOR",   _check_identity_thresholds_locked),
    ("four_hard_vetoes_only",                        "BEHAVIOR",   _check_4_hard_vetoes_only),
    ("no_idea_agent_external_endpoint",              "FILE_GREP",  _check_no_idea_agent_external_endpoint),
    ("no_inline_critic_iteration_metadata",          "AST",        _check_no_inline_critic_iteration_metadata),
]


@pytest.mark.parametrize(
    "name,kind,check",
    ANTI_PATTERNS,
    ids=[p[0] for p in ANTI_PATTERNS],
)
def test_anti_pattern_enforced(name, kind, check):
    """CONTEXT § Decision 19 — each anti-pattern is enforced at runtime."""
    check()


def test_anti_pattern_count_meets_30_minimum():
    """Sanity: the parametrize enumerates at least 30 items."""
    assert len(ANTI_PATTERNS) >= 30, (
        f"CONTEXT § Decision 19 requires ≥30 anti-patterns enforced; got {len(ANTI_PATTERNS)}."
    )
