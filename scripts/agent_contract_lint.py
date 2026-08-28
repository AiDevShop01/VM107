"""agent_contract_lint.py — standalone CI-lint cross-walking VM107 agent profiles
against the agent-catalogue governance corpus (Phase 167, AGV-03/AGV-04).

Cross-walks ``registry/agent_profile/*.yaml`` (the runtime manifest) against
``Documentation/Agent Zero/agent-catalogue/**/*.md`` frontmatter, joining the two
through the mandatory ``canon()`` normalizer (the 3-way id inconsistency: strip a
leading ``vm107.``, drop a dotted ``._role`` sub-profile suffix, snake->kebab, lower).
Runs the three parity checks from catalogue ``09 §5``:

    (a) a registry profile with no catalogue entry            (orphan profile)
    (b) a catalogue entry missing a required Contract field   (missing field)
    (c) a catalogue<->profile disagreement on tools/authority (authority drift)

Standalone by design (D-04/D-08): depends on ``pyyaml`` ONLY — python-frontmatter is
NOT installed, and this script never imports the VM107 app runtime. YAML/frontmatter
is parsed with ``yaml.safe_load`` only (never ``yaml.load`` — ASVS V5 / T-167-01);
malformed frontmatter is skipped with a WARN, never a crash.

Defaults to WARN mode (always exit 0 — P167A). ``--block`` flips the exit policy to
1-on-any-finding — the P167D enforcement lever, left OFF until the last wave (D-02).

Usage:
    cd /Volumes/HardDrive/FinGPT/VM107
    python scripts/agent_contract_lint.py            # WARN mode (P167A) — always exit 0
    python scripts/agent_contract_lint.py --block    # BLOCK mode (P167D) — exit 1 on findings

Exits:
    0 — no findings, OR WARN mode (always 0)
    1 — one or more findings (BLOCK mode only)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import yaml  # 6.0.3 — the only YAML lib in the tree; python-frontmatter is NOT installed

# ---------------------------------------------------------------------------
# Defaults + module-level contract
# ---------------------------------------------------------------------------

DEFAULT_PROFILE_DIR = _VM107_ROOT / "registry" / "agent_profile"
DEFAULT_CATALOGUE_DIR = _VM107_ROOT.parent / "Documentation" / "Agent Zero" / "agent-catalogue"

# Infra/framework personas excluded from contract authoring + the lint join (D-07).
# Post-canon() values.
#
# P170 (170-05, D-01a): `vm107.specialized_critics` is NOT an agent persona — it is the
# sole authoritative `critic_definition:` lens-config INDEX (no tools, no invoke, no LLM
# engine), presence/schema-validated by its OWN boot check (CRITIC_DEF_BOOT_STRICT), not the
# agent_contract: check. Excluded here so the agent-persona contract gate never false-flags
# it as a canon-base profile missing agent_contract:, mirroring the default/agent-zero/vm107
# infra exclusions.
EXCLUDED_IDS = {"default", "agent-zero", "vm107", "specialized-critics"}

# The required catalogue frontmatter fields (from agent-catalogue/_TEMPLATE.md). This
# list — together with REQUIRED_CONTRACT_SECTIONS below — IS the schema every authoring
# plan (167-03..07) conforms to. Extend here to tighten the contract fleet-wide.
REQUIRED_CONTRACT_FIELDS = [
    "agent",
    "family",
    "status",
    "authority",
    "trigger",
    "contract_version",
]

# The 14 numbered Contract sections every per-agent .md must fill, in order
# (agent-catalogue/_TEMPLATE.md §3). check-(b) asserts each heading is present.
REQUIRED_CONTRACT_SECTIONS = list(range(1, 15))


@dataclass(frozen=True)
class Finding:
    """A single lint finding. ``check`` is 'a'|'b'|'c' (a real finding) or 'warn'."""

    check: str
    agent: str
    message: str


class FrontmatterError(Exception):
    """Raised when a .md has a broken/malformed frontmatter fence (WARN + skip)."""


# ---------------------------------------------------------------------------
# Join-key normalization (E-CRIT2 — the load-bearing correctness point)
# ---------------------------------------------------------------------------


def canon(agent_id: str) -> str:
    """Canonical join key: strip leading ``vm107.``, drop a dotted ``._role`` suffix,
    snake->kebab, lowercase.

    canon('vm107.growth_domain_analyst') == 'growth-domain-analyst'
    canon('behavioral_mentor_agent._reader') == 'behavioral-mentor-agent'
    canon('macro_agent') == 'macro-agent'
    """
    base = str(agent_id).removeprefix("vm107.")
    base = base.split(".")[0]  # collapse ._reader/._analyzer/._writer onto the parent
    return base.replace("_", "-").lower()


def is_subprofile(agent_id: str) -> bool:
    """True if ``agent_id`` is a nested ``._role`` sub-profile (collapses onto a parent).

    A sub-profile carries a dot AFTER the optional ``vm107.`` prefix is removed.
    """
    return "." in str(agent_id).removeprefix("vm107.")


# ---------------------------------------------------------------------------
# Dependency-free frontmatter reader (no python-frontmatter — D-08)
# ---------------------------------------------------------------------------


def read_frontmatter(md_path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body) via a pyyaml fence-split.

    Raises ``FrontmatterError`` on a malformed/unterminated fence or non-mapping
    frontmatter, so callers can WARN-and-skip instead of crashing (T-167-01).
    """
    md_path = Path(md_path)
    text = md_path.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise FrontmatterError(f"unterminated frontmatter fence in {md_path.name}")
    try:
        meta = yaml.safe_load(parts[1])  # ALWAYS safe_load (never yaml.load — ASVS V5)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"malformed frontmatter yaml in {md_path.name}: {exc}") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise FrontmatterError(f"frontmatter is not a mapping in {md_path.name}")
    return meta, parts[2]


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _missing_contract_fields(meta: dict, body: str) -> list[str]:
    """Required frontmatter fields + the 14 numbered sections absent from an entry."""
    missing = [f for f in REQUIRED_CONTRACT_FIELDS if meta.get(f) in (None, "", [])]
    for n in REQUIRED_CONTRACT_SECTIONS:
        if not re.search(rf"(?m)^#+\s*{n}\.", body):
            missing.append(f"section {n}")
    return missing


def _section_tools(body: str) -> list[str]:
    """Backtick-quoted tool names documented under the ``## 6. Tools`` heading."""
    tools: list[str] = []
    in_six = False
    for line in body.splitlines():
        heading = re.match(r"^#+\s*(\d+)\.", line)
        if heading:
            in_six = heading.group(1) == "6"
            continue
        if in_six:
            tools.extend(re.findall(r"`([^`]+)`", line))
    return tools


# ---------------------------------------------------------------------------
# The three checks
# ---------------------------------------------------------------------------


def run_checks(profile_dir: Path, catalogue_dir: Path) -> list[Finding]:
    """Cross-walk profiles ⋈ catalogue and return all findings (empty = clean).

    Sub-profiles collapse onto their canon-base parent for checks (a) and (c): a
    role-scoped ``._reader``/``._analyzer``/``._writer`` narrower allow-list is NEVER
    compared against the single parent catalogue §6 (which would false-disagree once
    167-09 runs ``--block``).
    """
    profile_dir = Path(profile_dir)
    catalogue_dir = Path(catalogue_dir)
    findings: list[Finding] = []

    # 1. Load catalogue entries (skip templates/_-prefixed + non-agent design docs).
    catalogue: dict[str, tuple[dict, str, Path]] = {}
    for md in sorted(catalogue_dir.glob("**/*.md")):
        if md.name.startswith("_"):
            continue
        try:
            meta, body = read_frontmatter(md)
        except FrontmatterError as exc:
            findings.append(Finding("warn", canon(md.stem), f"skipped catalogue: {exc}"))
            continue
        agent = meta.get("agent")
        if not agent:
            continue  # README / numbered design docs — not per-agent specs
        key = canon(agent)
        catalogue[key] = (meta, body, md)
        # check-(b): catalogue entry missing a required Contract field.
        missing = _missing_contract_fields(meta, body)
        if missing:
            findings.append(Finding("b", key, "missing required Contract field(s): " + ", ".join(missing)))

    # 2. Load registry profiles — canon-base only (sub-profiles collapse onto parent).
    base_profiles: dict[str, dict] = {}
    for yml in sorted(profile_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yml.read_text()) or {}
        except yaml.YAMLError as exc:
            findings.append(Finding("warn", canon(yml.stem), f"skipped profile: {exc}"))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", canon(yml.stem), "profile is not a mapping"))
            continue
        agent_id = str(data.get("id", yml.stem))
        key = canon(agent_id)
        if key in EXCLUDED_IDS:
            continue
        if is_subprofile(agent_id):
            continue  # collapsed onto its canon-base parent
        base_profiles[key] = data

    # 3. check-(a): a base profile with no catalogue entry.
    for key in sorted(base_profiles):
        if key not in catalogue:
            findings.append(Finding("a", key, "registry profile has no catalogue entry"))

    # 4. check-(c): tools/authority disagreement (canon-base profile vs catalogue §6/§10).
    for key in sorted(base_profiles):
        if key not in catalogue:
            continue
        meta, body, _md = catalogue[key]
        data = base_profiles[key]
        allowed = set(data.get("allowed_tools") or [])
        denied = set(data.get("denied_tools") or [])
        cat_tools = _section_tools(body)
        # A tool the catalogue documents but the profile does not grant (or denies).
        undisclosed = sorted({t for t in cat_tools if t not in allowed or t in denied})
        if undisclosed:
            findings.append(
                Finding("c", key, "catalogue §6 tools not granted by profile: " + ", ".join(undisclosed))
            )

    return findings


# ---------------------------------------------------------------------------
# Exit-policy wrapper + CLI
# ---------------------------------------------------------------------------


def run_lint(
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    catalogue_dir: Path = DEFAULT_CATALOGUE_DIR,
    block: bool = False,
    verbose: bool = False,
) -> int:
    """Run the checks and return an exit code.

    WARN mode (default) always returns 0. ``block=True`` returns 1 on any real
    finding (checks a/b/c) — WARN-only 'skipped' findings never fail the build.
    """
    findings = run_checks(profile_dir, catalogue_dir)
    real = [f for f in findings if f.check in ("a", "b", "c")]
    warns = [f for f in findings if f.check == "warn"]

    if verbose:
        label = {"a": "ORPHAN", "b": "MISSING-FIELD", "c": "TOOLS-DISAGREE"}
        for f in real:
            print(f"  [{label[f.check]}] {f.agent}: {f.message}")
        for f in warns:
            print(f"  [WARN] {f.agent}: {f.message}")
        mode = "BLOCK" if block else "WARN"
        print(f"\n{len(real)} finding(s), {len(warns)} warning(s) — mode={mode}")
        if real and not block:
            print("WARN mode: exiting 0 (flip --block at P167D to enforce).")

    if block and real:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-walk registry/agent_profile ⋈ agent-catalogue for contract parity."
    )
    parser.add_argument(
        "--block",
        action="store_true",
        help="Exit 1 on any finding (P167D enforcement lever). Default: WARN (always exit 0).",
    )
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--catalogue-dir", default=str(DEFAULT_CATALOGUE_DIR))
    args = parser.parse_args(argv)
    return run_lint(
        Path(args.profile_dir),
        Path(args.catalogue_dir),
        block=args.block,
        verbose=True,
    )


if __name__ == "__main__":
    sys.exit(main())
