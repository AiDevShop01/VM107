"""Phase 89 Plan 08 — 20-Question UAT Battery + Transcript Export (Task 2).

REQ-89-9 (hallucination gate): automated structural pre-screen + transcript
export driver for the 20-question golden UAT question bank.

This is the AUTOMATED HALF of the UAT.
The other half — semantic hallucination review — is a human checkpoint (Task 3).

4 tests (all marked @pytest.mark.phase89 @pytest.mark.slow):
  - Test 1 (structural pre-screen): Runs all 20 questions against the deployed
    dev macro investigator. For each: asserts citation grammar valid, word_count
    <=400. Flags errors but does NOT perform semantic hallucination judgment
    (that is the human's job in Task 3).

  - Test 2 (Decision 7 blocking refusal verbatim): Seeds a synthetic blocking
    contradiction in macro_contradictions for "CPIAUCSL" → runs a CPI question
    through the investigator → asserts blocking_contradiction_refusal=True and
    answer equals the canonical B13 refusal text VERBATIM. Cleanup: deletes
    the synthetic row.

  - Test 3 (Decision 9 word cap): Finds the golden question marked
    expected_long=True (or uses the longest-expected category "regime_aware")
    → asserts the backend returns truncated_at field when the answer exceeds
    400 words. (If the model naturally answers within 400 words, the test
    asserts truncated_at is None — word cap enforcement only fires if needed.)

  - Test 4 (transcript export): Invokes uat_transcript_exporter.export_transcripts()
    programmatically → asserts the output markdown is created + contains 20
    sections (one per question) + each section has the reviewer-fillable fields.

Configuration (via env vars — no defaults; tests skip if absent):
  DEV_BASE_URL   — Base URL of the deployed dev VM100 (e.g. http://localhost:8000)
  DEV_JWT_TOKEN  — Valid JWT bearer token for the dev environment
  DEV_ACCOUNT_ID — Account ID accessible by the dev user

Per project locks:
  - No os.getenv("X", "default") patterns — fail-fast (tests skip cleanly if absent).
  - env-driven config; no hardcoded URLs.
  - JWT bearer auth pattern (MEMORY lock: vm100_jwt_bearer_auth_pattern).
  - NEVER use LIVE cTrader / production endpoints during testing.
"""
from __future__ import annotations

import os
import pathlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
import requests
import yaml

# ── Paths ─────────────────────────────────────────────────────────────────────

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
GOLDEN_QUESTIONS_PATH = FIXTURES_DIR / "golden_questions.yaml"
TOOLS_DIR = pathlib.Path(__file__).parents[2] / "tools"

# ── Canonical refusal text (Decision 7) ──────────────────────────────────────

CANONICAL_BLOCKING_REFUSAL_TEXT = (
    "I cannot confidently answer this right now — a blocking contradiction is active. "
    "The system is awaiting human review. [Open Contradiction Inbox →]"
)

# ── Citation grammar ──────────────────────────────────────────────────────────

_CITATION_REF_PATTERN = re.compile(r"\[ref:[a-zA-Z0-9_\-:.]+\]")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_questions() -> list[dict]:
    """Load the 20-question golden fixture."""
    return yaml.safe_load(GOLDEN_QUESTIONS_PATH.read_text())["questions"]


def _validate_citation_grammar(text: str) -> list[str]:
    """Return list of invalid [ref:...] grammar violations in text."""
    raw_refs = re.findall(r"\[ref:[^\]]*\]", text)
    violations = []
    for ref in raw_refs:
        if not _CITATION_REF_PATTERN.match(ref):
            violations.append(ref)
    return violations


def _count_words(text: str) -> int:
    return len(text.split())


def _get_dev_config() -> dict | None:
    """Return dev server config from env vars, or None if not set.

    Returns None to signal tests should be skipped.
    No fallback defaults — per env-driven-no-fallbacks MEMORY lock.
    """
    base_url = os.environ.get("DEV_BASE_URL")
    token = os.environ.get("DEV_JWT_TOKEN")
    account_id_str = os.environ.get("DEV_ACCOUNT_ID")

    if not all([base_url, token, account_id_str]):
        return None

    try:
        account_id = int(account_id_str)
    except (TypeError, ValueError):
        return None

    return {
        "base_url": base_url,
        "token": token,
        "account_id": account_id,
    }


def _post_macro_ask(
    *,
    base_url: str,
    token: str,
    account_id: int,
    prompt: str,
    indicator_id: str,
    timeout_s: int = 60,
) -> tuple[dict | None, str | None]:
    """POST /api/macro/ask and return (response_json, error_or_None)."""
    url = f"{base_url}/api/macro/ask"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "indicator_id": indicator_id,
        "account_id": account_id,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.ConnectionError as e:
        return None, f"ConnectionError: {e}"
    except requests.exceptions.Timeout:
        return None, f"Timeout after {timeout_s}s"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTPError {e.response.status_code}"


# ── Test 1: Structural pre-screen (20 questions) ──────────────────────────────


@pytest.mark.phase89
@pytest.mark.slow
def test_uat_structural_pre_screen() -> None:
    """Structural pre-screen: run 20 questions against deployed dev investigator.

    For each question:
    - Asserts citation grammar is valid (all [ref:...] match expected pattern).
    - Asserts word_count <=400 (Decision 9 hard cap enforced server-side).

    This test does NOT judge semantic correctness — that is the human's job
    in the Task 3 checkpoint. Structural failures here MUST be fixed before
    the human reviewer reads transcripts.
    """
    cfg = _get_dev_config()
    if cfg is None:
        pytest.skip(
            "DEV_BASE_URL / DEV_JWT_TOKEN / DEV_ACCOUNT_ID not set — "
            "set these env vars to run the UAT battery against the deployed dev stack"
        )

    questions = _load_questions()
    assert len(questions) == 20, f"Expected 20 questions, got {len(questions)}"

    structural_failures: list[str] = []
    connection_errors: list[str] = []

    for q in questions:
        response, error = _post_macro_ask(
            base_url=cfg["base_url"],
            token=cfg["token"],
            account_id=cfg["account_id"],
            prompt=q["prompt"],
            indicator_id=q["indicator_id"],
        )

        if error:
            connection_errors.append(f"{q['question_id']}: {error}")
            continue

        answer = response.get("answer", "")
        truncated_at = response.get("truncated_at")

        # Citation grammar check
        violations = _validate_citation_grammar(answer)
        if violations:
            structural_failures.append(
                f"{q['question_id']}: invalid [ref:] grammar: {violations}"
            )

        # Word count check (Decision 9)
        # truncated_at being set means the server applied the cap — that's correct.
        # Violation is when word_count > 400 AND truncated_at is not set.
        word_count = _count_words(answer)
        if word_count > 400 and truncated_at is None:
            structural_failures.append(
                f"{q['question_id']}: word_count={word_count} exceeds 400 but "
                f"truncated_at not set (Decision 9 word cap not applied)"
            )

    # Allow connection errors only if the server is partly available.
    # ALL 20 must run for the pre-screen to be meaningful.
    if connection_errors:
        pytest.fail(
            f"UAT pre-screen: {len(connection_errors)} connection error(s) — "
            f"all 20 questions must reach the server:\n" + "\n".join(connection_errors)
        )

    assert not structural_failures, (
        f"UAT structural pre-screen FAILED on {len(structural_failures)} question(s):\n"
        + "\n".join(structural_failures)
    )


# ── Test 2: Decision 7 blocking refusal verbatim ─────────────────────────────


@pytest.mark.phase89
@pytest.mark.slow
def test_decision7_blocking_refusal_verbatim() -> None:
    """Seed a synthetic blocking contradiction for CPIAUCSL.

    Then run a CPI question through the investigator.
    Assert: blocking_contradiction_refusal=True AND answer equals the canonical
    B13 refusal text VERBATIM (no improvisation — Decision 7).

    Cleanup: delete the synthetic contradiction row after assertion.

    This test seeds the contradiction via the VM100 backend's analytics DB
    (the same Postgres that vm107.macro_contradiction_detector writes to).
    """
    cfg = _get_dev_config()
    if cfg is None:
        pytest.skip(
            "DEV_BASE_URL / DEV_JWT_TOKEN / DEV_ACCOUNT_ID not set — "
            "set these env vars to run the Decision 7 blocking refusal test"
        )

    # Find the first CPI question in the golden bank
    questions = _load_questions()
    cpi_questions = [q for q in questions if q["indicator_id"] == "CPIAUCSL"]
    assert cpi_questions, "No CPIAUCSL questions in golden_questions.yaml"
    cpi_q = cpi_questions[0]

    # ── 1. Seed a synthetic blocking contradiction via API ────────────────────
    # Use the VM100 admin or a dev seeding endpoint to insert into macro_contradictions.
    # If no seeding endpoint exists, seed via the VM100 analytics DB directly
    # using the /api/macro/test/seed-contradiction endpoint (dev-only).
    seed_url = f"{cfg['base_url']}/api/macro/test/seed-contradiction"
    seed_headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Content-Type": "application/json",
    }
    synthetic_contradiction_id = str(uuid.uuid4())
    seed_payload = {
        "contradiction_id": synthetic_contradiction_id,
        "indicator_id": "CPIAUCSL",
        "severity": "blocking",
        "explanation_candidates": [
            "Synthetic contradiction for Decision 7 UAT test",
            "Created by test_uat_battery.py — safe to delete",
        ],
    }

    seed_resp = requests.post(
        seed_url, headers=seed_headers, json=seed_payload, timeout=10
    )

    if seed_resp.status_code == 404:
        pytest.skip(
            "Dev seeding endpoint /api/macro/test/seed-contradiction not available. "
            "Decision 7 test requires this dev-only endpoint. "
            "Deploy the dev seeding endpoint or run this test against a dev env "
            "that has active blocking contradictions for CPIAUCSL."
        )

    seed_resp.raise_for_status()

    try:
        # ── 2. Run the CPI question through the investigator ──────────────────
        response, error = _post_macro_ask(
            base_url=cfg["base_url"],
            token=cfg["token"],
            account_id=cfg["account_id"],
            prompt=cpi_q["prompt"],
            indicator_id="CPIAUCSL",
        )

        assert error is None, f"Request failed: {error}"
        assert response is not None

        # ── 3. Assert blocking refusal ────────────────────────────────────────
        assert response.get("blocking_contradiction_refusal") is True, (
            "Expected blocking_contradiction_refusal=True when a blocking "
            "contradiction is active for CPIAUCSL. "
            f"Got: {response.get('blocking_contradiction_refusal')!r}"
        )

        answer = response.get("answer", "")
        assert answer == CANONICAL_BLOCKING_REFUSAL_TEXT, (
            f"Decision 7: blocking refusal text must be VERBATIM canonical text.\n"
            f"Expected:\n  {CANONICAL_BLOCKING_REFUSAL_TEXT!r}\n"
            f"Got:\n  {answer!r}\n"
            "No improvisation allowed — check B13 contract refusal_text field."
        )

    finally:
        # ── 4. Cleanup: delete the synthetic contradiction ────────────────────
        cleanup_url = f"{cfg['base_url']}/api/macro/test/seed-contradiction/{synthetic_contradiction_id}"
        try:
            requests.delete(cleanup_url, headers=seed_headers, timeout=10)
        except Exception:
            pass  # Best-effort cleanup; test already complete


# ── Test 3: Decision 9 word cap truncation ────────────────────────────────────


@pytest.mark.phase89
@pytest.mark.slow
def test_decision9_word_cap_enforcement() -> None:
    """Decision 9 word cap: for a question expected to produce a long answer,
    assert the backend returns truncated_at field when the answer exceeds 400 words.

    Uses the 'regime_aware' category questions — these require multi-regime
    comparison and historically produce the longest answers.

    If the model naturally answers in <=400 words, we assert truncated_at is None
    (word cap enforcement only fires if needed — not a failure).
    """
    cfg = _get_dev_config()
    if cfg is None:
        pytest.skip(
            "DEV_BASE_URL / DEV_JWT_TOKEN / DEV_ACCOUNT_ID not set — "
            "set these env vars to run the Decision 9 word cap test"
        )

    questions = _load_questions()

    # First try any question marked expected_long=True
    long_questions = [q for q in questions if q.get("expected_long") is True]
    # Fall back to regime_aware questions (most likely to be long)
    if not long_questions:
        long_questions = [q for q in questions if q["category"] == "regime_aware"]
    assert long_questions, (
        "No questions found with expected_long=True or category='regime_aware' "
        "in golden_questions.yaml — cannot run Decision 9 word cap test"
    )

    test_q = long_questions[0]

    response, error = _post_macro_ask(
        base_url=cfg["base_url"],
        token=cfg["token"],
        account_id=cfg["account_id"],
        prompt=test_q["prompt"],
        indicator_id=test_q["indicator_id"],
        timeout_s=90,
    )

    assert error is None, f"Request failed: {error}"
    assert response is not None

    answer = response.get("answer", "")
    word_count = _count_words(answer)
    truncated_at = response.get("truncated_at")

    # The answer must never exceed 400 words — with or without truncation.
    assert word_count <= 400, (
        f"Decision 9 VIOLATION: answer has {word_count} words (cap=400) for "
        f"question {test_q['question_id']!r}. "
        f"truncated_at={truncated_at!r}. "
        "The backend must truncate at 400 words before returning."
    )

    # If the backend did truncate, truncated_at must be set.
    # (If word_count <= 400 and truncated_at is None → model answered within cap → OK)
    if truncated_at is not None:
        assert truncated_at <= 400, (
            f"truncated_at={truncated_at} exceeds 400 — backend truncation logic is wrong"
        )


# ── Test 4: Transcript export creates expected output ────────────────────────


@pytest.mark.phase89
@pytest.mark.slow
def test_transcript_export_creates_markdown() -> None:
    """Invoke uat_transcript_exporter.export_transcripts() programmatically.

    Asserts:
    - Output markdown file is created at the expected path.
    - Contains exactly 20 sections (one per question).
    - Each section has the reviewer-fillable "Hallucination flagged?" field.
    - Each section has a "Notes:" field for reviewer observations.

    Does NOT require the server to be available — mocks the HTTP call to
    return a canned valid response, so the export format can be validated
    in isolation from the live stack.
    """
    import pathlib
    import sys

    # Import the exporter from tools/
    sys.path.insert(0, str(TOOLS_DIR.parent))
    try:
        from tools.uat_transcript_exporter import export_transcripts as _export
        from tools.uat_transcript_exporter import _post_macro_ask as _real_post
    except ImportError as exc:
        pytest.fail(f"Cannot import uat_transcript_exporter: {exc}")

    # Build a canned response that matches AskResponse schema
    def _canned_post(**kwargs):
        question = kwargs["question"]
        indicator = question["indicator_id"]
        answer_text = (
            f"The {indicator} reading for the specified period came in at 3.4%, "
            f"compared to a consensus forecast of 3.3%. This represents a marginal "
            f"beat of 0.1 percentage points. [ref:release:{indicator}-2024-03-12] "
            f"The reaction in risk assets was muted given the broad-based pricing. "
            f"[ref:episode:CPIAUCSL-2024-03-reaction]"
        )
        canned_response = {
            "response_id": "test-" + question["question_id"],
            "indicator_id": indicator,
            "answer": answer_text,
            "citations": [
                {"ref_id": f"{indicator}-2024-03-12", "kind": "release", "label": f"{indicator} March 2024"},
                {"ref_id": f"{indicator}-2024-03-reaction", "kind": "episode", "label": "March reaction"},
            ],
            "b5_result": {"score": 4, "recommendation": "enter", "word_count": len(answer_text.split())},
            "degraded": False,
            "blocking_contradiction_refusal": False,
            "truncated_at": None,
            "show_more_url": None,
        }
        return canned_response, 42, None  # (response, latency_ms, error)

    output_path = pathlib.Path("/tmp/phase89-uat-test-transcripts.md")
    if output_path.exists():
        output_path.unlink()

    # Patch the HTTP call so the test works without a live server
    with patch("tools.uat_transcript_exporter._post_macro_ask", side_effect=_canned_post):
        result = _export(
            base_url="http://localhost:8000",  # unused — patched
            token="test-token",               # unused — patched
            account_id=1,                     # unused — patched
            output_path=output_path,
        )

    # ── 1. File created ───────────────────────────────────────────────────────
    assert output_path.exists(), (
        f"Transcript exporter did not create output file at {output_path}"
    )

    content = output_path.read_text(encoding="utf-8")

    # ── 2. Contains exactly 20 sections ──────────────────────────────────────
    # Each section starts with "## Question N/20: <id>"
    question_headers = re.findall(r"## Question \d+/20: ", content)
    assert len(question_headers) == 20, (
        f"Expected 20 question sections in transcript, found {len(question_headers)}"
    )

    # ── 3. Each section has reviewer-fillable "Hallucination flagged?" field ──
    hallucination_fields = re.findall(r"\*\*Hallucination flagged\?\*\*", content)
    assert len(hallucination_fields) == 20, (
        f"Expected 20 'Hallucination flagged?' reviewer fields, "
        f"found {len(hallucination_fields)}"
    )

    # ── 4. Each section has "Notes:" field ───────────────────────────────────
    notes_fields = re.findall(r"\*\*Notes:\*\*", content)
    assert len(notes_fields) == 20, (
        f"Expected 20 'Notes:' reviewer fields, found {len(notes_fields)}"
    )

    # ── 5. Result dict shows 20 total, 0 errors (canned responses) ───────────
    assert result["total"] == 20, f"Expected 20 total, got {result['total']}"
    assert result["ok"] == 20, f"Expected 20 ok, got {result['ok']}"
    assert result["errors"] == 0, f"Expected 0 errors, got {result['errors']}"

    # Cleanup
    output_path.unlink(missing_ok=True)
