"""Phase 133 (P1) Plan 03 — A4 tool-class cache unit proof.

Proves that ``helpers.modules.load_classes_from_file`` is memoized by absolute
path + base class (``_TOOL_CLASS_CACHE``):

- Two consecutive loads of the same (path, base_class) return the SAME list
  object and ``import_module`` (the ``spec.loader.exec_module`` re-exec cost) is
  invoked exactly ONCE across both calls.
- ``purge_namespace()`` (the dev hot-reload path) clears the cache so the next
  load re-imports (D-05 caveat).

Self-contained (no Qdrant, no container): a fake module carrying a subclass of a
locally-defined base is returned by a monkeypatched ``import_module`` so the test
never depends on a real tool file importing cleanly (litellm/etc. absent in CI).
The ``simpleeval`` stub lets ``helpers.modules`` (-> ``helpers.files``) import in
a minimal environment.
"""

import sys
import types
from pathlib import Path

# --- Minimal-environment shims (before importing helpers.modules) -------------
# helpers.modules -> helpers.files imports `simpleeval` at module load; this test
# never exercises it. Stub it if absent so the unit test runs anywhere.
if "simpleeval" not in sys.modules:
    try:  # pragma: no cover - present in the container venv
        import simpleeval  # noqa: F401
    except ImportError:  # pragma: no cover - minimal/CI env
        _se = types.ModuleType("simpleeval")
        _se.simple_eval = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["simpleeval"] = _se

# sys.path-inject import pattern (test_collection_separation.py:76-80 shape).
_VM107 = Path("/Volumes/ HardDrive/FinGPT/VM107")
if str(_VM107) not in sys.path:
    sys.path.insert(0, str(_VM107))

import pytest  # noqa: E402

from helpers import modules  # noqa: E402
from helpers.modules import (  # noqa: E402
    _TOOL_CLASS_CACHE,
    load_classes_from_file,
    purge_namespace,
)


class _Base:
    """Standalone base class (avoids importing helpers.tool -> litellm)."""


class _Sub(_Base):
    """A subclass load_classes_from_file should discover in the fake module."""


def _make_fake_module():
    m = types.ModuleType("fake_tool_module")
    m.SomeTool = _Sub  # discovered by inspect.getmembers(..., isclass)
    return m


@pytest.mark.integration
def test_load_classes_from_file_is_memoized_and_purge_clears(monkeypatch):
    """Second load hits the cache (identity + single exec); purge empties it."""
    _TOOL_CLASS_CACHE.clear()

    calls = {"n": 0}
    fake_module = _make_fake_module()

    def _counting_import(file):
        calls["n"] += 1
        return fake_module

    # Patch the name load_classes_from_file resolves at call time.
    monkeypatch.setattr(modules, "import_module", _counting_import)

    path = "tools/_p1_cache_probe.py"  # arbitrary; import_module is stubbed

    first = load_classes_from_file(path, _Base)
    second = load_classes_from_file(path, _Base)

    # Cache hit: same list object returned, exec ran exactly once.
    assert first is second, "second load did not return the cached list (no memo)"
    assert calls["n"] == 1, f"import_module re-executed ({calls['n']}x) — memo missed"
    assert first == [_Sub], "load_classes_from_file did not resolve the subclass"

    # Sanity: the cache is keyed and populated.
    assert len(_TOOL_CLASS_CACHE) == 1

    # Dev hot-reload path clears the memo.
    purge_namespace("fake_tool_module")
    assert _TOOL_CLASS_CACHE == {}, "purge_namespace did not clear _TOOL_CLASS_CACHE"

    # After purge the next load re-imports (exec count increments again).
    third = load_classes_from_file(path, _Base)
    assert calls["n"] == 2, "post-purge load did not re-import"
    assert third is not first, "post-purge load returned the stale cached list"
