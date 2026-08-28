import os
from pathlib import Path

from agent import AgentConfig
from helpers import runtime, settings, defer, extension
from helpers.print_style import PrintStyle
from helpers.agent_yaml_v2_validator import (
    validate_agent_yaml_v2,
    AgentYamlV2Error,
    is_v2_profile,
)


@extension.extensible
def initialize_capability_registry() -> None:
    """Phase 47.6 — boot CapabilityRegistry from env-driven path.

    Env-driven config; no fallback default (project memory rule + LD-1).
    CAPABILITY_REGISTRY_ROOT must be set in docker-compose.yml / .env.production.

    Raises:
        SystemExit: If CAPABILITY_REGISTRY_ROOT is not set, or if any of the
                    7 registry validation stages fail (LD-2 hard-fail discipline).

    This function is idempotent in the sense that CapabilityRegistry.initialize()
    raises RuntimeError if called twice — run_ui.py calls initialize_capability_registry()
    exactly once before any agent dispatch.
    """
    from core.registry.capability_registry import CapabilityRegistry
    from fingpt_core.contracts.capability_registry import RegistryValidationError

    try:
        registry_root = Path(os.environ["CAPABILITY_REGISTRY_ROOT"])
    except KeyError as exc:
        raise SystemExit(
            "CAPABILITY_REGISTRY_ROOT env var REQUIRED. "
            "No fallback default per project memory rule + LD-1. "
            "Set in docker-compose.yml / .env.production."
        ) from exc

    try:
        CapabilityRegistry.initialize(registry_root)
        snapshot = CapabilityRegistry.get().snapshot
        PrintStyle().print(
            f"CapabilityRegistry initialized: "
            f"entries={len(snapshot.entries)} "
            f"hash={snapshot.snapshot_hash[:16]}…"
        )
    except RegistryValidationError as exc:
        # Phase 73-followup escape hatch: opt-in soft-fail for live UAT/dev
        # when Phase 72/73 yaml-schema drift is being remediated separately.
        # PRODUCTION default is hard-fail (LD-2). Setting CAPABILITY_REGISTRY_PERMISSIVE=1
        # downgrades the failure to a loud warning so VM107 can boot while the
        # registry data is being repaired phase-by-phase. NEVER ship this flag
        # set in prod env.
        if os.environ.get("CAPABILITY_REGISTRY_PERMISSIVE") == "1":
            PrintStyle().print(
                f"WARN: CapabilityRegistry validation FAILED but PERMISSIVE mode is on — "
                f"VM107 will boot anyway. Fix registry YAMLs before disabling permissive. "
                f"Error: {exc}"
            )
        else:
            raise SystemExit(
                f"CapabilityRegistry validation FAILED — VM107 cannot start (LD-2 hard-fail). "
                f"Fix registry YAMLs and restart. Error: {exc}"
            ) from exc
    except RuntimeError:
        # Already initialized (e.g., re-import in test context). Not an error.
        pass


@extension.extensible
def initialize_agent(override_settings: dict | None = None):
    current_settings = settings.get_settings()
    if override_settings:
        current_settings = settings.merge_settings(current_settings, override_settings)

    # agent configuration - models are now resolved at call time via _model_config plugin
    config = AgentConfig(
        profile=current_settings["agent_profile"],
        knowledge_subdirs=[current_settings["agent_knowledge_subdir"], "default"],
        mcp_servers=current_settings["mcp_servers"],
    )

    # update config with runtime args
    _args_override(config)

    # initialize MCP in deferred task to prevent blocking the main thread
    # async def initialize_mcp_async(mcp_servers_config: str):
    #     return initialize_mcp(mcp_servers_config)
    # defer.DeferredTask(thread_name="mcp-initializer").start_task(initialize_mcp_async, config.mcp_servers)
    # initialize_mcp(config.mcp_servers)

    # import helpers.mcp_handler as mcp_helper
    # import agent as agent_helper
    # import helpers.print_style as print_style_helper
    # if not mcp_helper.MCPConfig.get_instance().is_initialized():
    #     try:
    #         mcp_helper.MCPConfig.update(config.mcp_servers)
    #     except Exception as e:
    #         first_context = agent_helper.AgentContext.first()
    #         if first_context:
    #             (
    #                 first_context.log
    #                 .log(type="warning", content=f"Failed to update MCP settings: {e}")
    #             )
    #         (
    #             print_style_helper.PrintStyle(background_color="black", font_color="red", padding=True)
    #             .print(f"Failed to update MCP settings: {e}")
    #         )

    # return config object
    return config

@extension.extensible
def initialize_chats():
    from helpers import persist_chat
    async def initialize_chats_async():
        persist_chat.load_tmp_chats()
    return defer.DeferredTask().start_task(initialize_chats_async)

@extension.extensible
def initialize_mcp():
    set = settings.get_settings()
    async def initialize_mcp_async():
        from helpers.mcp_handler import initialize_mcp as _initialize_mcp
        return _initialize_mcp(set["mcp_servers"])
    return defer.DeferredTask().start_task(initialize_mcp_async)

@extension.extensible
def initialize_job_loop():
    from helpers.job_loop import run_loop
    return defer.DeferredTask("JobLoop").start_task(run_loop)

@extension.extensible
def initialize_preload():
    import preload
    return defer.DeferredTask().start_task(preload.preload)

@extension.extensible
def initialize_migration():
    from helpers import migration, dotenv
    # run migration
    migration.startup_migration()
    # reload .env as it might have been moved
    dotenv.load_dotenv()
    # reload settings to ensure new paths are picked up
    settings.reload_settings()

@extension.extensible
def initialize_validate_phase60_profiles():
    """Phase 60.1 (G8): hard-fail on invalid v2 profiles at container startup.

    Iterates every SubAgent loaded from VM107/agents/ via subagents.get_agents_dict()
    (which reads the agents/*/agent.yaml persona dirs ONLY — it does NOT touch the
    registry/agent_profile/*.yaml manifests, despite an earlier version of this
    docstring claiming otherwise). Calls validate_agent_yaml_v2() on each.
    v1 profiles (schema_version=None) get a deprecation warning, not a fail.
    v2 profiles with semantic errors halt container startup.

    The registry/agent_profile/ manifests are validated by the separate, additive,
    env-gated initialize_validate_agent_contracts() hook (Phase 167 / AGV-05).

    This hook is invoked by run_ui.py during boot, after initialize_migration().
    CTX-§7 LOCKED: invalid v2 profiles must NEVER reach runtime with None defaults.

    Implementation note: get_agents_dict() returns lightweight SubAgentListItem
    objects (no v2 fields). To perform semantic validation we must call
    load_agent_data(name) which returns the full SubAgent with all v2 fields
    populated from agent.yaml. The mock path (used in tests) lets callers
    substitute get_agents_dict() with a dict of pre-built SubAgent instances.
    """
    from helpers import subagents

    # get_agents_dict() returns SubAgentListItem (lightweight) — used for the
    # mock path in tests. For real boot, load each profile via load_agent_data()
    # to get the full SubAgent with v2 fields for semantic validation.
    list_dict = subagents.get_agents_dict() if hasattr(subagents, "get_agents_dict") else {}

    # Detect mock path: if any value has schema_version attribute, callers already
    # injected full SubAgent-like objects (unit test scenario). Otherwise, use
    # load_agent_data() to get the full SubAgent for each profile.
    first_val = next(iter(list_dict.values()), None)
    mock_path = first_val is not None and hasattr(first_val, "schema_version")

    if mock_path:
        profiles_to_check: dict[str, object] = dict(list_dict)
    else:
        profiles_to_check = {}
        for profile_name in list_dict:
            try:
                sub = subagents.load_agent_data(profile_name)
                profiles_to_check[profile_name] = sub
            except Exception:
                # If we can't load it, skip — load_agent_data itself may warn
                pass

    errors: list[tuple[str, Exception]] = []
    for profile_name, sub in profiles_to_check.items():
        try:
            validate_agent_yaml_v2(profile_name, sub)
        except AgentYamlV2Error as exc:
            errors.append((profile_name, exc))
        except Exception as exc:  # treat unknown exceptions as fatal too
            errors.append((profile_name, exc))

    if errors:
        msg = "; ".join(f"{p}: {e}" for p, e in errors)
        raise AgentYamlV2Error(f"Phase 60 boot validation failed for {len(errors)} profile(s): {msg}")

    return len(profiles_to_check)


@extension.extensible
def initialize_validate_agent_contracts(profile_dir: Path | None = None) -> int:
    """Phase 167 (AGV-05 / P167D): presence-validate the agent_contract: block on every
    canon-base registry manifest — a NEW, additive, env-gated boot hook.

    This is a genuinely new code path (D-08 / research Fact 2): the older
    initialize_validate_phase60_profiles() reads ONLY the agents/*/agent.yaml persona
    dirs via get_agents_dict() and structurally never sees the registry manifests. This
    hook globs registry/agent_profile/*.yaml directly, yaml.safe_load()s each (ALWAYS
    safe_load — ASVS V5 / T-167-01), and asserts each in-scope canon-base profile carries
    an agent_contract: block. It does PRESENCE/PARITY ONLY — it NEVER mutates a profile.

    Env-gate with the INVERTED default (D-02 fragile-tree guard — a prior session bricked
    this tree, so the security-safe default is to never brick boot):

        CONTRACT_BOOT_STRICT absent OR != "1"  => WARN-and-continue (never raises)
        CONTRACT_BOOT_STRICT == "1"            => raise SystemExit on any finding

    This mirrors the CAPABILITY_REGISTRY_PERMISSIVE precedent above but inverts its
    default (permissive/warn by default; strict is opt-in). The strict raise is the
    security-POSITIVE state, flipped ON only after the all-green gate + the 167-09 live
    verify — reversible by unsetting the flag with NO code change.

    Scope (reuses canon() + EXCLUDED_IDS from scripts/agent_contract_lint.py — the SAME
    normalizer the lint uses, never forked):
      * The 3 infra profiles (default / agent_zero / vm107) are skipped (D-07) — never
        counted, never a finding.
      * The 9 nested ._role sub-profiles (behavioral_mentor / trade_auditor /
        weekly_review × _reader/_analyzer/_writer) INHERIT their canon-base parent's
        contract (167-07 decision): the presence check runs on the parent ONLY, so a
        blockless sub-profile MUST NOT independently produce a missing-block finding.

    Args:
        profile_dir: glob root for the manifests. Defaults to VM107/registry/agent_profile/
                     (the real corpus); tests point it at a fixture dir.

    Returns:
        The count of canon-base (in-scope, non-excluded, non-sub-profile) manifests validated.

    Raises:
        SystemExit: ONLY when CONTRACT_BOOT_STRICT == "1" AND >=1 canon-base manifest is
                    missing its agent_contract: block.
    """
    import yaml  # 6.0.3 — the only YAML lib in the tree; safe_load ONLY (ASVS V5)

    # Reuse the lint's exact join-key normalizer + infra allowlist (do not fork).
    from scripts.agent_contract_lint import canon, EXCLUDED_IDS, is_subprofile

    if profile_dir is None:
        profile_dir = Path(__file__).resolve().parent / "registry" / "agent_profile"
    profile_dir = Path(profile_dir)

    strict = os.environ.get("CONTRACT_BOOT_STRICT") == "1"

    validated = 0
    missing: list[str] = []
    for yml in sorted(profile_dir.glob("*.yaml")):
        if yml.name.startswith("_"):
            # Template/scaffold manifest (e.g. _TEMPLATE.yaml) — not a shippable agent.
            # Never counted, never a finding (P169-05: closes a latent CONTRACT_BOOT_STRICT
            # boot-brick introduced when a `_TEMPLATE.yaml` landed in registry/agent_profile/).
            continue
        try:
            data = yaml.safe_load(yml.read_text()) or {}
        except yaml.YAMLError as exc:
            # Malformed manifest => WARN + skip, never arbitrary code (T-167-01).
            PrintStyle().print(f"WARN: skipping unparseable profile {yml.name}: {exc}")
            continue
        if not isinstance(data, dict):
            PrintStyle().print(f"WARN: skipping non-mapping profile {yml.name}")
            continue

        agent_id = str(data.get("id", yml.stem))
        key = canon(agent_id)
        if key in EXCLUDED_IDS:
            continue  # infra persona (D-07) — never counted, never a finding
        if is_subprofile(agent_id):
            continue  # nested ._role sub-profile — inherits the canon-base parent (167-07)

        validated += 1
        if "agent_contract" not in data:
            missing.append(f"{yml.name} ({agent_id})")

    if missing:
        detail = "; ".join(missing)
        if strict:
            raise SystemExit(
                f"CONTRACT_BOOT_STRICT: {len(missing)} registry profile(s) missing "
                f"agent_contract: block — VM107 cannot start (AGV-05). "
                f"Author the block(s) and restart, or unset CONTRACT_BOOT_STRICT to boot. "
                f"Missing: {detail}"
            )
        PrintStyle().print(
            f"WARN: {len(missing)} profile(s) missing agent_contract: block (boot continues; "
            f"set CONTRACT_BOOT_STRICT=1 to enforce). Missing: {detail}"
        )

    # --- P169 (169-05, D-11 / AGV-09 / AGV-11): additive domain_definition: check ---
    # Presence + schema validation of the net-new `domain_definition:` block on the 12
    # vm107.*_domain_analyst.yaml manifests, delegated to DomainDefinition.from_profile
    # (yaml.safe_load ONLY — ASVS V5 / T-169-05-01; presence/schema ONLY — never mutates).
    #
    # Gated with its OWN inverted-default flag DOMAIN_DEF_BOOT_STRICT (independent of
    # CONTRACT_BOOT_STRICT) — the fragile-tree guard (D-02 / Pitfall 3): absent/!=1 =>
    # WARN-and-continue (boot NEVER bricks); ==1 => raise SystemExit. Left OFF in this
    # phase; flipped ON only after all-green + the Plan 07 live verify. Reversible by
    # unsetting the flag with NO code change (T-169-05-02).
    dd_strict = os.environ.get("DOMAIN_DEF_BOOT_STRICT") == "1"
    dd_findings: list[str] = []
    try:
        from core.agents.domain_definition import DomainDefinition
    except Exception as exc:  # loader import failure => a finding, never a bare crash
        DomainDefinition = None  # type: ignore[assignment]
        dd_findings.append(f"<domain_definition loader import>: {type(exc).__name__}: {exc}")

    if DomainDefinition is not None:
        for yml in sorted(profile_dir.glob("vm107.*_domain_analyst.yaml")):
            try:
                DomainDefinition.from_profile(str(yml))  # safe_load + schema validation
            except Exception as exc:
                dd_findings.append(f"{yml.name}: {type(exc).__name__}: {exc}")

    if dd_findings:
        dd_detail = "; ".join(dd_findings)
        if dd_strict:
            raise SystemExit(
                f"DOMAIN_DEF_BOOT_STRICT: {len(dd_findings)} domain-analyst profile(s) with a "
                f"missing/invalid domain_definition: block — VM107 cannot start (AGV-09/AGV-11). "
                f"Author/fix the block(s) and restart, or unset DOMAIN_DEF_BOOT_STRICT to boot. "
                f"Findings: {dd_detail}"
            )
        PrintStyle().print(
            f"WARN: {len(dd_findings)} domain-analyst profile(s) with missing/invalid "
            f"domain_definition: block (boot continues; set DOMAIN_DEF_BOOT_STRICT=1 to enforce). "
            f"Findings: {dd_detail}"
        )

    return validated


def _args_override(config):
    # update config with runtime args
    for key, value in runtime.args.items():
        if hasattr(config, key):
            # conversion based on type of config[key]
            if isinstance(getattr(config, key), bool):
                value = value.lower().strip() == "true"
            elif isinstance(getattr(config, key), int):
                value = int(value)
            elif isinstance(getattr(config, key), float):
                value = float(value)
            elif isinstance(getattr(config, key), str):
                value = str(value)
            else:
                raise Exception(
                    f"Unsupported argument type of '{key}': {type(getattr(config, key))}"
                )

            setattr(config, key, value)



