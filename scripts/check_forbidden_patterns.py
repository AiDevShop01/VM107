#!/usr/bin/env python3
"""Phase 43.2 — pre-commit hook: forbid direct LiteLLM/parse calls outside allowlist.

Scans each staged Python file passed on argv. Skips files matching any allowlist prefix.
For non-allowlisted files, scans non-comment lines for forbidden regex patterns.
On violation: prints remediation message, exits 1.
On clean scan: exits 0.

Companion: tests/lint/test_no_direct_llm_calls.py — codebase-wide walker (CI source of truth).

ALLOWLIST (paths permitted to use the patterns below):
  - core/routing/                   (failover wrapper, scoring, schemas)
  - core/agents/structured_output.py  (the safe_parse module itself)
  - core/contracts/                 (legitimate Pydantic validation callers)
  - extensions/python/              (CONTEXT.md: extension that owns the wrapper;
                                     references unified_call as monkey-patch target)
  - models.py                       (LiteLLMChatWrapper.unified_call IS the wrapper)
  - tests/                          (tests legitimately exercise these patterns)
  - scripts/check_forbidden_patterns.py  (this script itself contains pattern strings)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# LOCKED — see CONTEXT.md Enforcement section.
# Each entry: (regex, label, remediation)
FORBIDDEN_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"\.parse_raw\(",
        "Pydantic v1 parse_raw (deprecated)",
        "Use schema.model_validate_json() — better: route through core/agents/structured_output.safe_parse()",
    ),
    (
        r"\.parse_obj\(",
        "Pydantic v1 parse_obj (deprecated)",
        "Use schema.model_validate() — better: route through safe_parse()",
    ),
    (
        r"\.model_validate_json\(",
        "Direct model_validate_json call",
        "Use core/agents/structured_output.safe_parse(output, schema) — never raises, handles malformed JSON",
    ),
    (
        r"\.model_validate\(",
        "Direct model_validate call",
        "Use core/agents/structured_output.safe_parse(output, schema) — never raises, handles malformed JSON",
    ),
    (
        r"litellm\.completion\(",
        "Direct litellm.completion call",
        "Use core/routing/router.ModelRouter.decide() + execute_with_fallback wrapper",
    ),
    (
        r"\.unified_call\(",
        "Direct .unified_call() invocation",
        "Wire through extensions/python/chat_model_call_before/_router_apply.py — calls execute_with_fallback",
    ),
    (
        r"\.with_structured_output\(",
        "Direct .with_structured_output() call",
        "Use core/agents/structured_output.bind_structured(llm, schema, agent_name) — returns None gracefully on unsupported providers",
    ),
]

# Paths permitted to use the patterns above (NOT a blacklist).
# Match is prefix-based: if rel_path.startswith(prefix) -> allowlisted.
ALLOWLIST_PREFIXES: list[str] = [
    "core/routing/",
    "core/agents/structured_output.py",
    "core/contracts/",
    "extensions/python/",                    # CONTEXT.md: extension that owns the wrapper
    "models.py",
    "tests/",
    "scripts/check_forbidden_patterns.py",   # this script contains the patterns as strings
]


def is_allowlisted(rel_path: str) -> bool:
    """Return True if the relative path is in the allowlist."""
    return any(rel_path.startswith(prefix) for prefix in ALLOWLIST_PREFIXES)


def scan_file(path: Path, vm107_root: Path) -> list[tuple[int, str, str, str]]:
    """Returns list of violations: (lineno, label, line_excerpt, remediation)."""
    rel = path.relative_to(vm107_root).as_posix()
    if is_allowlisted(rel):
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    violations: list[tuple[int, str, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for regex, label, remediation in FORBIDDEN_PATTERNS:
            if re.search(regex, line):
                violations.append((lineno, label, stripped[:120], remediation))
                break  # one violation per line is enough
    return violations


def main(argv: list[str]) -> int:
    vm107_root = Path(__file__).resolve().parent.parent
    files = [Path(arg).resolve() for arg in argv]

    all_violations: list[tuple[Path, list]] = []
    for path in files:
        if not path.exists() or path.suffix != ".py":
            continue
        try:
            path.relative_to(vm107_root)
        except ValueError:
            continue  # skip files outside VM107 (shouldn't happen via pre-commit)
        violations = scan_file(path, vm107_root)
        if violations:
            all_violations.append((path, violations))

    if not all_violations:
        return 0

    print("ERROR: Forbidden LiteLLM/parse patterns found outside allowlist:", file=sys.stderr)
    for path, viols in all_violations:
        for lineno, label, excerpt, remediation in viols:
            print(f"  {path}:{lineno}: {label}", file=sys.stderr)
            print(f"    > {excerpt}", file=sys.stderr)
            print(f"    Fix: {remediation}", file=sys.stderr)
    print("\nAllowlist (paths permitted to use these patterns):", file=sys.stderr)
    for prefix in ALLOWLIST_PREFIXES:
        print(f"  - {prefix}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
