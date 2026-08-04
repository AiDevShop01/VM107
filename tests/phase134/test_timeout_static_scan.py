"""SC-1 RED gate — every guarded sync-client / POST site must carry a client-native timeout.

Phase 134 Wave 0 (Nyquist RED-first). This is a STATIC source scan (it does NOT import the
guarded modules) that enumerates every SC-1 site by module path + connector token and asserts
the corresponding timeout kwarg appears inside each connector call's argument span.

MUST FAIL today (RED): all sites are un-timed (`MongoClient(...)` without
`serverSelectionTimeoutMS`, `psycopg2.connect(...)` without `connect_timeout`, `QdrantClient(...)`
without `timeout`, `requests.post(...)` without `timeout`). Wave 1 (134-03/05) adds the kwargs
in place to turn this green. If the fix is reverted, this gate goes red again.

grep-gate hygiene: full-line `#` comments are stripped before matching so header prose cannot
self-satisfy the scan, and each site asserts a NON-ZERO call count so a moved/renamed site
cannot pass as "0 found".
"""
import os

# repo root = two levels up from tests/phase134/
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# (module_path_relative_to_repo, connector_token, required_timeout_kwarg, human_label)
# The connector token ends with "(" so its last char marks the opening paren of the call.
GUARDED_SITES = [
    # --- Mongo: serverSelectionTimeoutMS ---
    ("core/boundary/budget_tracker.py",                                "MongoClient(",     "serverSelectionTimeoutMS", "mongo/budget_tracker"),
    ("core/runtime/envelope_repo.py",                                  "MongoClient(",     "serverSelectionTimeoutMS", "mongo/envelope_repo"),
    ("core/belief/belief_store.py",                                    "MongoClient(",     "serverSelectionTimeoutMS", "mongo/belief_store"),
    ("core/interfaces/progress_ledger.py",                             "MongoClient(",     "serverSelectionTimeoutMS", "mongo/progress_ledger"),
    ("core/interfaces/task_ledger.py",                                 "MongoClient(",     "serverSelectionTimeoutMS", "mongo/task_ledger"),
    ("extensions/python/util_model_call_before/_20_router_decide.py",  "MongoClient(",     "serverSelectionTimeoutMS", "mongo/util_router_decide"),
    ("extensions/python/util_model_call_after/_20_router_log_cost.py", "MongoClient(",     "serverSelectionTimeoutMS", "mongo/util_router_log_cost"),
    # --- Postgres: connect_timeout ---
    ("core/belief/belief_store.py",                                    "psycopg2.connect(", "connect_timeout",         "pg/belief_store"),
    ("core/discovery/edge_proposer.py",                               "psycopg2.connect(", "connect_timeout",         "pg/edge_proposer"),
    ("core/discovery/throughput_governor.py",                         "psycopg2.connect(", "connect_timeout",         "pg/throughput_governor"),
    ("core/contradiction/contradiction_engine.py",                    "psycopg2.connect(", "connect_timeout",         "pg/contradiction_engine"),
    # --- Qdrant: timeout ---
    ("plugins/_memory/backend/factory.py",                            "QdrantClient(",     "timeout",                 "qdrant/factory"),
    # --- outbound POST: timeout ---
    ("core/alerts/phase91_emit.py",                                   "requests.post(",    "timeout",                 "post/phase91_emit"),
]


def _strip_comment_lines(src: str) -> str:
    """Drop full-line `#` comments (grep-gate hygiene) before any matching."""
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


def _call_arg_spans(src: str, token: str) -> list[str]:
    """Return the paren-balanced argument text of every `token` call (multi-line safe)."""
    spans: list[str] = []
    idx = 0
    while True:
        hit = src.find(token, idx)
        if hit == -1:
            break
        open_paren = hit + len(token) - 1  # token ends with "("
        depth = 0
        i = open_paren
        while i < len(src):
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans.append(src[open_paren + 1:i])
        idx = i + 1
    return spans


def test_guarded_site_registry_is_complete():
    """The in-test registry must enumerate every SC-1 site (>=12)."""
    assert len(GUARDED_SITES) >= 12, (
        f"SC-1 registry must enumerate >=12 guarded sites; has {len(GUARDED_SITES)}"
    )


def test_all_guarded_sites_carry_a_timeout():
    """RED today: no un-timed guarded connect/POST site may remain."""
    untimed: list[str] = []
    for rel_path, token, kwarg, label in GUARDED_SITES:
        abs_path = os.path.join(_REPO_ROOT, rel_path)
        assert os.path.isfile(abs_path), f"missing guarded module: {rel_path}"
        with open(abs_path, encoding="utf-8") as fh:
            src = _strip_comment_lines(fh.read())
        spans = _call_arg_spans(src, token)
        # NON-ZERO expected count: a moved/renamed site cannot silently pass as "0 found".
        assert len(spans) >= 1, (
            f"{label}: expected >=1 `{token}` call in {rel_path}, found 0 "
            f"(site moved? update GUARDED_SITES)"
        )
        for args in spans:
            if kwarg not in args:
                untimed.append(f"{label} ({rel_path}): `{token}...)` missing `{kwarg}`")
    assert not untimed, (
        "SC-1 RED — un-timed guarded sites remain:\n  " + "\n  ".join(untimed)
    )
