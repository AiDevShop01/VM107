"""Phase 87 Wave 4b — deterministic story-update skill.

Pure-Python decisions on top of LLM candidate headlines: CREATE / REINFORCE /
RETIRE / DROP. The macro_story_tracker agent calls these from its hourly
tick (see ``agent.py``); writes to the ``macro_story`` Postgres table happen
through a separate repo (``persist/macro_story_repo.py``).

Policy constants (locked by Plan 87-08 must-haves):

* ``MAX_ACTIVE_STORIES = 10`` — bound the story-noise risk register.
* ``CONFIDENCE_FLOOR = 0.5`` — refuse to create low-conviction stories.
* ``SIMILARITY_THRESHOLD = 0.85`` — cosine threshold (over) ⇒ REINFORCE
  existing instead of CREATE new (embedding dedup, NOT string match).

LOCK-7 retirement rule: when a story's supporting_indicators have ≥3
consecutive opposite-direction releases, ``check_retirement`` returns
``(True, reason)``; the agent then writes a new WORM row with
``supersedes_story_id`` pointing back at the active story and
``is_active=False``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from math import sqrt

MAX_ACTIVE_STORIES = 10
CONFIDENCE_FLOOR = 0.5
SIMILARITY_THRESHOLD = 0.85  # cosine — above this ⇒ REINFORCE existing


@dataclass
class StoryUpdateDecision:
    """One-shot decision returned by ``decide_update``.

    Attributes:
        action: ``"CREATE"`` / ``"REINFORCE"`` / ``"DROP"`` (RETIRE is
            handled by the separate ``check_retirement`` flow).
        story_id: For REINFORCE, the existing story's UUID. For CREATE,
            a fresh UUID the caller should persist. For DROP, a throwaway
            UUID (callers should ignore).
        reason: Human-readable rationale (lands in the envelope payload).
    """

    action: str
    story_id: uuid.UUID
    reason: str


def decide_update(
    *,
    candidate_headline: str,
    candidate_embedding: list[float],
    candidate_confidence: float,
    supporting_release_id: str,
    supporting_indicators: list[str],
    active_stories: list[dict],
    embedding_service,
) -> StoryUpdateDecision:
    """Return the CREATE / REINFORCE / DROP decision for one candidate headline.

    Decision tree per plan 87-08 interfaces:

    1. If no active stories:
       - confidence < floor ⇒ DROP
       - else ⇒ CREATE
    2. Otherwise, find max cosine similarity vs active stories' embeddings.
       - If best > SIMILARITY_THRESHOLD ⇒ REINFORCE (return that story's id)
       - confidence < floor ⇒ DROP
       - at cap ⇒ DROP
       - else ⇒ CREATE (new uuid)

    The ``embedding_service`` argument is accepted for forward-compat (the
    real ``MacroStoryTracker.run_once`` already embedded the candidate
    before calling this function), but is not invoked here — embeddings are
    pre-computed by the caller and passed in as ``candidate_embedding`` /
    ``active_stories[*]["headline_embedding"]``.

    Args:
        candidate_headline: The LLM-emitted candidate headline string.
        candidate_embedding: 768-dim Phase 58 embedding of the headline.
        candidate_confidence: LLM-emitted confidence in ``[0, 1]``.
        supporting_release_id: economic_event id the candidate derived from.
        supporting_indicators: indicator ids implicated by the candidate.
        active_stories: rows from ``macro_story`` with ``is_active=true``
            — each carries ``story_id`` (str/UUID) and
            ``headline_embedding`` (list[float]).
        embedding_service: Phase 58 EmbeddingService — reserved for future
            on-demand embedding of active-story headlines that were
            persisted without an embedding column.

    Returns:
        ``StoryUpdateDecision`` describing the action to take.
    """
    if not active_stories:
        if candidate_confidence < CONFIDENCE_FLOOR:
            return StoryUpdateDecision(
                action="DROP",
                story_id=uuid.uuid4(),
                reason=(
                    f"confidence {candidate_confidence:.2f} < floor "
                    f"{CONFIDENCE_FLOOR}"
                ),
            )
        return StoryUpdateDecision(
            action="CREATE",
            story_id=uuid.uuid4(),
            reason="no active stories",
        )

    best_story: dict | None = None
    best_sim = 0.0
    for s in active_stories:
        sim = _cosine(candidate_embedding, s["headline_embedding"])
        if sim > best_sim:
            best_sim = sim
            best_story = s

    if best_story is not None and best_sim > SIMILARITY_THRESHOLD:
        return StoryUpdateDecision(
            action="REINFORCE",
            story_id=_coerce_uuid(best_story["story_id"]),
            reason=(
                f"similar (cos={best_sim:.3f}) to story "
                f"{best_story['story_id']}"
            ),
        )

    if candidate_confidence < CONFIDENCE_FLOOR:
        return StoryUpdateDecision(
            action="DROP",
            story_id=uuid.uuid4(),
            reason=(
                f"confidence {candidate_confidence:.2f} < floor "
                f"{CONFIDENCE_FLOOR}"
            ),
        )

    if len(active_stories) >= MAX_ACTIVE_STORIES:
        return StoryUpdateDecision(
            action="DROP",
            story_id=uuid.uuid4(),
            reason=(
                f"at MAX_ACTIVE_STORIES ({MAX_ACTIVE_STORIES})"
            ),
        )

    return StoryUpdateDecision(
        action="CREATE",
        story_id=uuid.uuid4(),
        reason="new pattern",
    )


def check_retirement(
    *,
    story: dict,
    recent_releases_by_indicator: dict[str, list[dict]],
) -> tuple[bool, str | None]:
    """LOCK-7 retirement check — ≥3 consecutive opposite-direction releases.

    For each indicator in ``story["supporting_indicators"]``, look at the
    last 3 release rows in ``recent_releases_by_indicator[indicator]``. If
    all 3 carry a ``surprise`` whose sign is the opposite of the story's
    implied direction (``story["implied_direction"]``, ±1), the story
    should be retired.

    Args:
        story: A row from ``macro_story`` with at least
            ``supporting_indicators`` (list[str]) and ``implied_direction``
            (int — +1 or -1).
        recent_releases_by_indicator: Mapping indicator_id ⇒ list of
            release dicts (each carrying a numeric ``surprise``), ordered
            oldest → newest.

    Returns:
        ``(True, reason)`` if any supporting indicator's last-3 releases
        all turned opposite-direction, else ``(False, None)``.
    """
    story_dir = int(story.get("implied_direction", +1))
    opposite_sign = -story_dir

    for indicator in story.get("supporting_indicators", []):
        history = recent_releases_by_indicator.get(indicator, [])
        last3 = history[-3:]
        if len(last3) < 3:
            continue

        all_opposite = True
        for r in last3:
            surprise = r.get("surprise", 0) or 0
            # opposite means sign(surprise) == opposite_sign (and non-zero)
            if opposite_sign > 0 and not surprise > 0:
                all_opposite = False
                break
            if opposite_sign < 0 and not surprise < 0:
                all_opposite = False
                break

        if all_opposite:
            return (
                True,
                f"3 consecutive opposite-direction {indicator} releases turned",
            )

    return False, None


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Returns 0.0 on degenerate inputs."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _coerce_uuid(value) -> uuid.UUID:
    """Accept UUID or stringified UUID — Postgres rows arrive as str."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
