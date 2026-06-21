"""Phase 89 Plan 08 — UAT Transcript Exporter.

CLI tool that runs the 20-question golden_questions.yaml battery against the
deployed dev macro investigator and exports per-question transcripts to a
reviewer-readable markdown file.

Usage:
    python tools/uat_transcript_exporter.py \
        --output 89-UAT-TRANSCRIPTS.md \
        --base-url http://localhost:8000 \
        --token "$DEV_JWT_TOKEN" \
        --account-id "$DEV_ACCOUNT_ID"

Per project locks:
  - env-driven config: no hardcoded URLs, no fallback defaults.
  - JWT bearer auth (Authorization: Bearer <token>) — NEVER credentials:include
    (vm100_jwt_bearer_auth_pattern MEMORY lock).

Output format: One section per question with reviewer-fillable fields:
  - Question metadata (id, category, indicator)
  - Prompt text
  - API response (answer, word_count, citations, b5_result)
  - blocking_contradiction_refusal + degraded flags
  - latency_ms
  - Reviewer-fillable: "Hallucination flagged?" + "Notes" per question

REQ-89-9: This exporter is the automation half of the UAT. The human half
(semantic hallucination review) is done by reading the output markdown.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests
import yaml

# ── Constants ─────────────────────────────────────────────────────────────────

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "tests" / "phase89" / "fixtures"
_GOLDEN_QUESTIONS_PATH = _FIXTURES_DIR / "golden_questions.yaml"

# Citation grammar: [ref:kind:id] or [ref:release:CPIAUCSL-2024-06-10] etc.
_CITATION_REF_PATTERN = re.compile(r"\[ref:[a-zA-Z0-9_\-:.]+\]")

# Canonical B13 refusal text (Decision 7 — must be verbatim)
CANONICAL_BLOCKING_REFUSAL_TEXT = (
    "I cannot confidently answer this right now — a blocking contradiction is active. "
    "The system is awaiting human review. [Open Contradiction Inbox →]"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_questions() -> list[dict]:
    """Load the 20-question golden fixture."""
    if not _GOLDEN_QUESTIONS_PATH.exists():
        raise FileNotFoundError(
            f"golden_questions.yaml not found at {_GOLDEN_QUESTIONS_PATH}. "
            "Was Phase 89 Wave 0 scaffolding complete?"
        )
    data = yaml.safe_load(_GOLDEN_QUESTIONS_PATH.read_text())
    return data["questions"]


def _validate_citation_grammar(text: str) -> list[str]:
    """Return list of invalid [ref:...] grammar violations in text.

    Valid: [ref:release:CPI-2026-06-10], [ref:edge:CPIAUCSL->DXY], [ref:belief:abc123]
    Invalid: [ref:] (empty), [ref::bad], [ref:bad bad] (spaces)
    """
    raw_refs = re.findall(r"\[ref:[^\]]*\]", text)
    violations = []
    for ref in raw_refs:
        if not _CITATION_REF_PATTERN.match(ref):
            violations.append(ref)
    return violations


def _count_words(text: str) -> int:
    """Count whitespace-delimited words in text."""
    return len(text.split())


def _post_macro_ask(
    *,
    base_url: str,
    token: str,
    account_id: int,
    question: dict,
    timeout_s: int = 60,
) -> tuple[dict | None, int, str | None]:
    """POST /api/macro/ask with a golden question.

    Returns (response_json, latency_ms, error_message_or_None).
    """
    url = f"{base_url}/api/macro/ask"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": question["prompt"],
        "indicator_id": question["indicator_id"],
        "account_id": account_id,
    }

    start = time.monotonic()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        return resp.json(), latency_ms, None
    except requests.exceptions.ConnectionError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return None, latency_ms, f"ConnectionError: {exc}"
    except requests.exceptions.Timeout as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return None, latency_ms, f"Timeout after {timeout_s}s: {exc}"
    except requests.exceptions.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return None, latency_ms, f"HTTPError {exc.response.status_code}: {exc}"


def _format_citations(citations: list[dict]) -> str:
    """Pretty-print citations as one line each."""
    if not citations:
        return "  (none)"
    lines = []
    for c in citations:
        ref_id = c.get("ref_id", "?")
        kind = c.get("kind", "?")
        label = c.get("label", "")
        label_part = f" — {label}" if label else ""
        lines.append(f"  - [ref:{kind}:{ref_id}]{label_part}")
    return "\n".join(lines)


def _format_b5_result(b5: dict | None) -> str:
    """Format B5 result for display."""
    if b5 is None:
        return "  (not present)"
    score = b5.get("score", "?")
    rec = b5.get("recommendation", "?")
    wc = b5.get("word_count", "?")
    return f"  score={score}, recommendation={rec!r}, word_count={wc}"


def _render_question_section(
    *,
    question: dict,
    response: dict | None,
    latency_ms: int,
    error: str | None,
    q_index: int,
    total: int,
) -> str:
    """Render one question's transcript section as markdown."""
    q_id = question["question_id"]
    category = question["category"]
    indicator = question["indicator_id"]
    prompt = question["prompt"]

    lines = [
        f"",
        f"---",
        f"",
        f"## Question {q_index}/{total}: {q_id}",
        f"",
        f"**Indicator:** `{indicator}`  ",
        f"**Category:** `{category}`  ",
        f"**Latency:** {latency_ms}ms",
        f"",
        f"### Prompt",
        f"",
        f"> {prompt}",
        f"",
    ]

    if error:
        lines += [
            f"### ERROR",
            f"",
            f"```",
            f"{error}",
            f"```",
            f"",
            f"### Reviewer",
            f"",
            f"**Hallucination flagged?** [ ] YES   [ ] NO",
            f"",
            f"**Notes:** _(error — no answer to review)_",
            f"",
        ]
        return "\n".join(lines)

    answer = response.get("answer", "")
    citations = response.get("citations", [])
    b5_result = response.get("b5_result")
    degraded = response.get("degraded", False)
    blocking = response.get("blocking_contradiction_refusal", False)
    truncated_at = response.get("truncated_at")
    word_count = _count_words(answer)

    # Citation grammar check
    citation_violations = _validate_citation_grammar(answer)

    lines += [
        f"### Answer",
        f"",
        f"**Word count:** {word_count}",
        f"**Truncated at:** {truncated_at if truncated_at else 'not truncated'}",
        f"**Degraded:** {'YES' if degraded else 'NO'}",
        f"**Blocking contradiction refusal:** {'YES' if blocking else 'NO'}",
        f"",
        answer,
        f"",
        f"### Citations",
        f"",
        _format_citations(citations),
        f"",
        f"### B5 Evaluation",
        f"",
        _format_b5_result(b5_result),
        f"",
    ]

    if citation_violations:
        lines += [
            f"### STRUCTURAL ISSUES (pre-screen)",
            f"",
            f"**Invalid [ref:] grammar found** ({len(citation_violations)} violation(s)):",
            f"",
        ]
        for v in citation_violations:
            lines.append(f"  - `{v}`")
        lines.append(f"")

    if word_count > 400:
        lines += [
            f"### STRUCTURAL ISSUES (pre-screen)",
            f"",
            f"**Word count {word_count} exceeds 400-word hard cap (Decision 9)**",
            f"",
        ]

    lines += [
        f"### Reviewer",
        f"",
        f"**Hallucination flagged?** [ ] YES   [ ] NO",
        f"",
        f"**Notes:** _(reviewer: was each citation above verified against the evidence drawer?)_",
        f"",
    ]

    return "\n".join(lines)


def export_transcripts(
    *,
    base_url: str,
    token: str,
    account_id: int,
    output_path: pathlib.Path,
    timeout_s: int = 60,
    verbose: bool = False,
) -> dict:
    """Run all 20 questions and write the transcript markdown file.

    Returns a summary dict:
    {
        "total": 20,
        "ok": N,
        "errors": M,
        "citation_violations": K,
        "word_count_violations": L,
        "output_path": str,
    }
    """
    questions = _load_questions()
    total = len(questions)

    header = [
        f"# Phase 89 UAT Transcripts",
        f"",
        f"**Generated:** {datetime.now(tz=timezone.utc).isoformat()}",
        f"**Base URL:** {base_url}",
        f"**Questions:** {total}",
        f"**Account ID:** {account_id}",
        f"",
        f"## Instructions",
        f"",
        f"For each question below:",
        f"1. Read the **Answer** section.",
        f"2. For each citation chip, verify the cited evidence actually supports the claim.",
        f"3. Mark **Hallucination flagged? YES** if a cited source does NOT contain data",
        f"   supporting the claim in the answer.",
        f"4. Mark calibration issues (partial support) as Notes — NOT as hallucination.",
        f"5. Tally total hallucinations at end of file.",
        f"",
        f"**Hallucination gate (REQ-89-9):** <=1/20 hallucinations → PASS; >1/20 → FAIL",
        f"",
        f"---",
        f"",
    ]

    sections = []
    ok_count = 0
    error_count = 0
    citation_violation_count = 0
    word_count_violation_count = 0

    for i, question in enumerate(questions, start=1):
        q_id = question["question_id"]
        if verbose:
            print(f"  [{i:02d}/{total}] {q_id}: {question['prompt'][:60]}...", flush=True)

        response, latency_ms, error = _post_macro_ask(
            base_url=base_url,
            token=token,
            account_id=account_id,
            question=question,
            timeout_s=timeout_s,
        )

        if error:
            error_count += 1
        else:
            ok_count += 1
            answer = response.get("answer", "")
            if _validate_citation_grammar(answer):
                citation_violation_count += 1
            if _count_words(answer) > 400:
                word_count_violation_count += 1

        section = _render_question_section(
            question=question,
            response=response,
            latency_ms=latency_ms,
            error=error,
            q_index=i,
            total=total,
        )
        sections.append(section)

    # Summary footer
    footer = [
        f"",
        f"---",
        f"",
        f"## UAT Tally",
        f"",
        f"**Questions run:** {total}",
        f"**Successful responses:** {ok_count}",
        f"**Errors (no response):** {error_count}",
        f"**Structural citation violations:** {citation_violation_count}",
        f"**Word count violations (>400 words):** {word_count_violation_count}",
        f"",
        f"### Hallucination Count (fill in after review)",
        f"",
        f"**Hallucination count:** ___/20",
        f"",
        f"**Gate decision:** [ ] PASS (<=1/20)   [ ] FAIL (>1/20)",
        f"",
        f"### Rubric Tuning Notes (if FAIL)",
        f"",
        f"_(reviewer: if gate fails, list which rubric checks need weight adjustment)_",
        f"",
    ]

    content = "\n".join(header) + "\n".join(sections) + "\n".join(footer)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    return {
        "total": total,
        "ok": ok_count,
        "errors": error_count,
        "citation_violations": citation_violation_count,
        "word_count_violations": word_count_violation_count,
        "output_path": str(output_path),
    }


# ── CLI entry point ───────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Phase 89 UAT transcripts to a markdown file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output markdown file path (e.g. 89-UAT-TRANSCRIPTS.md)",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="VM100 base URL (e.g. http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="JWT bearer token for authenticated requests",
    )
    parser.add_argument(
        "--account-id",
        required=True,
        type=int,
        help="Account ID to use for all requests",
    )
    parser.add_argument(
        "--timeout",
        default=60,
        type=int,
        help="Per-request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stdout as questions are run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_path = pathlib.Path(args.output)

    if args.verbose:
        print(f"Phase 89 UAT Transcript Exporter")
        print(f"  Base URL:   {args.base_url}")
        print(f"  Account ID: {args.account_id}")
        print(f"  Output:     {output_path}")
        print(f"  Questions:  20 (from golden_questions.yaml)")
        print()

    result = export_transcripts(
        base_url=args.base_url,
        token=args.token,
        account_id=args.account_id,
        output_path=output_path,
        timeout_s=args.timeout,
        verbose=args.verbose,
    )

    print(f"\nTranscript export complete:")
    print(f"  Questions:             {result['total']}")
    print(f"  OK responses:          {result['ok']}")
    print(f"  Errors:                {result['errors']}")
    print(f"  Citation violations:   {result['citation_violations']}")
    print(f"  Word count violations: {result['word_count_violations']}")
    print(f"  Output:                {result['output_path']}")

    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
