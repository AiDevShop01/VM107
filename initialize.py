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

    Iterates every SubAgent loaded from VM107/agents/ AND every entry under
    VM107/registry/agent_profile/. Calls validate_agent_yaml_v2() on each.
    v1 profiles (schema_version=None) get a deprecation warning, not a fail.
    v2 profiles with semantic errors halt container startup.

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



