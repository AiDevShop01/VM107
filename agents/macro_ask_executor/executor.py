"""Phase 155 — MacroAskExecutor (PLACEHOLDER, real implementation lands in 155-03).

155-02 scope is the two leaf components (the AZE-07 ``subagent_contract`` envelope and the
``PillarSnapshotFetcher``). The full ``MacroAskExecutor`` orchestrator — registry-gated
resolver, AZE-07 fail-loud dispatch, async fan-out, and the ``synthesize`` handoff — is the
155-03 deliverable (``registry_adapter.py`` + ``resolver.py`` + this module, min 60 lines).

Why this placeholder exists (155-02 Rule 3 unblock): the Wave-0 RED scaffold
``tests/phase155/test_subagent_contract.py`` imports ``MacroAskExecutor`` at MODULE TOP
(line 22), so without an importable ``agents.macro_ask_executor.executor`` the entire module
fails at COLLECTION — taking the three pure AZE-07 *shape* tests (which 155-02 owns and must
turn GREEN) down with the three *dispatch* tests (which 155-03 owns and must stay RED). This
stub makes the module import so the shape tests run GREEN while the dispatch tests stay RED
(``dispatch_one`` / ``run`` / ``build_subagent_request`` are deliberately NOT defined →
``AttributeError`` → RED until 155-03).

155-03 NOTE: this file is REPLACED wholesale by the real orchestrator. Read it before
overwriting (Write requires a prior Read of an existing file).
"""

from __future__ import annotations


class MacroAskExecutor:
    """Placeholder — see module docstring. Real orchestrator ships in 155-03.

    Accepts the constructor kwargs the 155-03 dispatch tests pass so construction itself
    does not error; the dispatch/run/build_subagent_request methods are intentionally
    withheld so those behaviours remain RED until 155-03 implements them.
    """

    def __init__(self, *, registry=None, pillar_fetcher=None, **_ignored) -> None:  # noqa: ANN001
        self._registry = registry
        self._pillar_fetcher = pillar_fetcher
