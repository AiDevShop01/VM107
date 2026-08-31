"""Phase 138 (P6 / F3 Seam 1) — tool dispatch extracted from agent.py:1189-1265.

Pure move: agent.get_tool's body, `self` -> `agent`. Behavior identical
(BUG-17 subdir fallback + D1 tri-state Unknown/FailedToLoad/class preserved).
The P1-A4 tool-class cache's future home wraps load_classes_from_file below.

Agent keeps a thin @extension.extensible delegator so the public surface + the
single runtime caller (process_tools @ agent.py:1020) are unchanged (SC-3, D-03).

Public API:
    get_tool(agent, name, method, args, message, loop_data, **kwargs) -> Tool
"""
from __future__ import annotations


def get_tool(agent, name, method, args, message, loop_data, **kwargs):
    # SC-2 (P7): time the tool-dispatch seam (resolve + load) into
    # SLORegistry('tool_dispatch'). Additive timing ONLY — the tri-state return
    # (Unknown / FailedToLoad / tool class) that Plan 04 guards is unchanged, and
    # the finally never swallows an exception raised by the dispatch body.
    # Imported lazily to keep get_tool host-importable (deps stay inside the body).
    import time as _time
    _slo_start = _time.perf_counter()
    try:
        return _get_tool_impl(agent, name, method, args, message, loop_data, **kwargs)
    finally:
        from core.observability.slo_registry import SLORegistry, observe_slo_latency
        _elapsed_ms = (_time.perf_counter() - _slo_start) * 1000.0
        SLORegistry.get_shared_instance().record("tool_dispatch", _elapsed_ms)
        # AZI-05 (154-05): cross-process export alongside the in-process record.
        observe_slo_latency("tool_dispatch", _elapsed_ms)


def _get_tool_impl(agent, name, method, args, message, loop_data, **kwargs):
    from tools.unknown import Unknown
    from tools.failed_to_load import FailedToLoad
    from helpers.tool import Tool
    from helpers import subagents, extract_tools

    classes = []

    # search for tools in agent's folder hierarchy
    paths = subagents.get_paths(agent, "tools", name + ".py")

    # BUG-17 (Phase 62.1): Tools in subdirs (tools/replay/, tools/adaptive/, etc.) are
    # invisible to flat name lookup. Fall back to recursive glob across all hierarchical
    # tools roots. Flat lookup still wins when both match — no behavior change for the
    # 100+ top-level tools that work today.
    if not paths:
        import glob as _glob
        import logging as _logging
        import os as _os
        _tools_roots = subagents.get_paths(agent, "tools", must_exist_completely=False)
        for _root in _tools_roots:
            if not _root or not _os.path.isdir(_root):
                continue
            _matches = _glob.glob(_os.path.join(_root, "**", name + ".py"), recursive=True)
            if _matches:
                _logging.getLogger("fingpt.agent.get_tool").debug(
                    "BUG-17 subdir fallback: resolved '%s' to %s", name, _matches[0]
                )
                paths = [_matches[0]]
                break

    # D1 (Phase 135): capture the last load error so a file that EXISTS on the
    # resolution path but fails to load is distinguishable from a missing name.
    # (Python clears the `as` target at the end of the except clause, so persist it.)
    _last_load_err: Exception | None = None
    for path in paths:
        try:
            classes = extract_tools.load_classes_from_file(path, Tool)  # type: ignore[arg-type]
            break
        except Exception as _load_err:
            _last_load_err = _load_err
            continue  # preserve BUG-17 multi-path fallback — try the next resolved path

    # D1 tri-state selection:
    #   no path anywhere        -> Unknown       (unchanged: tool genuinely not found)
    #   path(s) found, all fail -> FailedToLoad  (exists-but-failed; log the real cause)
    #   a path loaded           -> that class
    if not paths:
        tool_class = Unknown
    elif not classes:
        import logging as _logging
        _logging.getLogger("fingpt.agent.get_tool").warning(
            "Tool '%s' found at %s but failed to load; returning FailedToLoad sentinel",
            name,
            paths[0],
            exc_info=_last_load_err,
        )
        tool_class = FailedToLoad
    else:
        tool_class = classes[0]
    return tool_class(
        agent=agent,
        name=name,
        method=method,
        args=args,
        message=message,
        loop_data=loop_data,
        **kwargs,
    )
