"""validate_phase60_profiles.py — Phase 60 agent profile validation script.

Validates the NESTED agent profile directories for Phase 60 (trade_auditor_agent,
behavioral_mentor_agent, weekly_review_agent) against the v2 schema rules.

Usage:
    cd /Volumes/HardDrive/FinGPT/VM107
    python scripts/validate_phase60_profiles.py                         # all profiles
    python scripts/validate_phase60_profiles.py --profile trade_auditor_agent

Validates:
    1. NESTED directory layout: top-level + _reader/_analyzer/_writer exist
    2. Each agent.yaml loads as SubAgent + passes validate_agent_yaml_v2()
    3. Reader role.md contains the literal "data, not instruction" substring (CTX-§14)
    4. Discovery layer: load_agent_data("<profile>._reader") resolves via 60-01 patch

Exits:
    0 — all validations pass
    1 — one or more validations failed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import yaml

from helpers.agent_yaml_v2_validator import validate_agent_yaml_v2, AgentYamlV2Error
from helpers.subagents import SubAgent, load_agent_data

# ---------------------------------------------------------------------------
# Phase 60 profile names (add as waves ship)
# ---------------------------------------------------------------------------

ALL_PROFILES = [
    "trade_auditor_agent",
    "behavioral_mentor_agent",  # Wave 3 (60-10)
    "weekly_review_agent",      # Wave 4 (60-11)
]

SUB_PROFILE_NAMES = ("_reader", "_analyzer", "_writer")

AGENTS_DIR = _VM107_ROOT / "agents"

# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def _load_subagent(yaml_path: Path) -> SubAgent:
    """Load a SubAgent from a YAML file."""
    data = yaml.safe_load(yaml_path.read_text())
    return SubAgent.model_validate(data or {})


def validate_profile(profile_name: str, verbose: bool = True) -> list[str]:
    """Validate a single Phase 60 top-level profile and its nested sub-profiles.

    Returns a list of failure messages (empty list = all pass).
    """
    failures: list[str] = []
    profile_dir = AGENTS_DIR / profile_name

    if not profile_dir.is_dir():
        failures.append(f"[{profile_name}] Profile directory missing: {profile_dir}")
        return failures  # No point continuing

    # 1. Validate top-level agent.yaml
    top_yaml = profile_dir / "agent.yaml"
    if not top_yaml.exists():
        failures.append(f"[{profile_name}] Missing top-level agent.yaml at {top_yaml}")
    else:
        try:
            agent = _load_subagent(top_yaml)
            validate_agent_yaml_v2(profile_name, agent)
            if verbose:
                print(f"  PASS [{profile_name}] top-level agent.yaml — v2 valid")
        except AgentYamlV2Error as exc:
            failures.append(f"[{profile_name}] v2 validation failed: {exc}")
        except Exception as exc:
            failures.append(f"[{profile_name}] load error: {exc}")

    # 2. Validate nested sub-profiles
    for sub_name in SUB_PROFILE_NAMES:
        sub_dir = profile_dir / sub_name
        dotted_id = f"{profile_name}.{sub_name}"

        if not sub_dir.is_dir():
            failures.append(f"[{dotted_id}] Nested sub-profile directory missing: {sub_dir}")
            continue

        sub_yaml = sub_dir / "agent.yaml"
        if not sub_yaml.exists():
            failures.append(f"[{dotted_id}] Missing agent.yaml at {sub_yaml}")
        else:
            try:
                agent = _load_subagent(sub_yaml)
                validate_agent_yaml_v2(dotted_id, agent)
                if verbose:
                    print(f"  PASS [{dotted_id}] agent.yaml — v2 valid")
            except AgentYamlV2Error as exc:
                failures.append(f"[{dotted_id}] v2 validation failed: {exc}")
            except Exception as exc:
                failures.append(f"[{dotted_id}] load error: {exc}")

        # 3. Check reader role.md for CTX-§14 doctrine sentinel
        if sub_name == "_reader":
            role_md = sub_dir / "prompts" / "agent.system.main.role.md"
            if not role_md.exists():
                failures.append(
                    f"[{dotted_id}] Missing reader role.md at {role_md}"
                )
            else:
                content = role_md.read_text()
                if "data, not instruction" not in content:
                    failures.append(
                        f"[{dotted_id}] CTX-§14 doctrine MISSING: "
                        f"'data, not instruction' not found in {role_md}"
                    )
                else:
                    if verbose:
                        print(f"  PASS [{dotted_id}] reader role.md contains CTX-§14 doctrine sentinel")

    # 4. Test discovery layer: load_agent_data("<profile>._reader") resolves
    reader_id = f"{profile_name}._reader"
    reader_dir = AGENTS_DIR / profile_name / "_reader"
    if reader_dir.is_dir():
        try:
            # Change working directory temporarily so helpers.files.get_abs_path resolves
            import os
            orig_cwd = os.getcwd()
            os.chdir(str(_VM107_ROOT))
            try:
                loaded = load_agent_data(reader_id)
                if loaded is None:
                    failures.append(
                        f"[{reader_id}] load_agent_data() returned None — "
                        "60-01 Task 1b discovery patch not working?"
                    )
                else:
                    if verbose:
                        print(f"  PASS [{reader_id}] load_agent_data() resolves via 60-01 discovery patch")
            finally:
                os.chdir(orig_cwd)
        except FileNotFoundError:
            failures.append(
                f"[{reader_id}] load_agent_data() raised FileNotFoundError — "
                "60-01 Task 1b discovery patch not working or nested dir missing"
            )
        except Exception as exc:
            failures.append(f"[{reader_id}] load_agent_data() error: {exc}")

    return failures


def validate_all_profiles(profile_names: list[str], verbose: bool = True) -> dict[str, list[str]]:
    """Validate all listed profiles. Returns dict of profile → failure list."""
    results: dict[str, list[str]] = {}
    for profile_name in profile_names:
        profile_dir = AGENTS_DIR / profile_name
        if not profile_dir.is_dir():
            if verbose:
                print(f"\n[{profile_name}] SKIP — directory not yet on disk (pending wave)")
            continue
        if verbose:
            print(f"\nValidating: {profile_name}")
        failures = validate_profile(profile_name, verbose=verbose)
        results[profile_name] = failures
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Phase 60 agent profiles against v2 schema rules."
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=(
            "Validate a single profile by name "
            "(default: validate all profiles that exist on disk)"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-field PASS messages; only show failures.",
    )
    args = parser.parse_args()

    verbose = not args.quiet

    if args.profile:
        profiles_to_check = [args.profile]
    else:
        profiles_to_check = ALL_PROFILES

    results = validate_all_profiles(profiles_to_check, verbose=verbose)

    # Summary
    total_failures = sum(len(v) for v in results.values())
    print()
    if total_failures == 0:
        print(f"All {len(results)} profile(s) validated — PASS")
        return 0
    else:
        print(f"FAILURES ({total_failures} total):")
        for profile_name, failures in results.items():
            for failure in failures:
                print(f"  FAIL {failure}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
