"""Phase 89 Plan 01 — wiring bug regression tests.

Tests for all four wiring bugs that caused production traffic to bypass
the macro_investigator stack (no system prompt, no citations, no B5,
no structured response envelope).

Bug 0: No A0 profile YAML at profiles/macro_investigator.yaml
Bug 1: response_self_check slot never fired in agent.py
Bug 2: VM107 returned {context_id, response} instead of AskResponse envelope
Bug 3: No system prompt instructing citation emission

Grouped into three test modules (one per commit scope):
  - TestProfileLoads        — Bug 0 + Bug 3 (profile YAML + prompt file exist)
  - TestResponseSelfCheckSlot — Bug 1 (slot wiring in agent.py source)
  - TestApiMessageEnvelope  — Bug 2 (structured envelope for macro_investigator)
"""
from __future__ import annotations

import ast
import pathlib

import pytest

VM107_ROOT = pathlib.Path(__file__).parent.parent.parent  # VM107/ root
PROFILES_DIR = VM107_ROOT / "profiles"
PROMPTS_DIR = VM107_ROOT / "prompts"
AGENT_PY = VM107_ROOT / "agent.py"
API_MESSAGE_PY = VM107_ROOT / "api" / "api_message.py"

# ---------------------------------------------------------------------------
# Bug 0 + Bug 3 — Profile YAML + system prompt exist and are correctly wired
# ---------------------------------------------------------------------------


class TestProfileLoads:
    """Bug 0 fix: A0-runtime profile at profiles/macro_investigator.yaml must exist."""

    def test_profile_yaml_exists(self):
        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        assert profile_path.exists(), (
            f"A0-runtime profile not found at {profile_path}. "
            "Bug 0: A0 falls back to default agent without this file."
        )

    def test_profile_has_prompt_field(self):
        import yaml

        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        profile = yaml.safe_load(profile_path.read_text())
        assert "prompt" in profile, (
            "Profile YAML must have a 'prompt:' field pointing at the system prompt."
        )

    def test_profile_prompt_file_exists(self):
        import yaml

        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        profile = yaml.safe_load(profile_path.read_text())
        prompt_ref = profile.get("prompt", "")
        # prompt field may be relative to A0 root (e.g. "VM107/prompts/...") or just a filename.
        # Resolve against VM107_ROOT and against the repo root (one level up).
        candidates = [
            VM107_ROOT / prompt_ref,
            VM107_ROOT.parent / prompt_ref,
            PROMPTS_DIR / pathlib.Path(prompt_ref).name,
        ]
        found = any(c.exists() for c in candidates)
        assert found, (
            f"Prompt file referenced in profile ({prompt_ref!r}) not found. "
            f"Searched: {[str(c) for c in candidates]}"
        )

    def test_profile_id_matches_investigator(self):
        import yaml

        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        profile = yaml.safe_load(profile_path.read_text())
        assert profile.get("id") == "vm107.macro_investigator", (
            f"Profile id must be 'vm107.macro_investigator', got {profile.get('id')!r}"
        )

    def test_profile_has_b5_self_eval(self):
        import yaml

        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        profile = yaml.safe_load(profile_path.read_text())
        assert profile.get("b5_self_eval") is True, (
            "Profile must have b5_self_eval: true (Decision 6)"
        )

    def test_profile_has_b5_rubric_id(self):
        import yaml

        profile_path = PROFILES_DIR / "macro_investigator.yaml"
        profile = yaml.safe_load(profile_path.read_text())
        assert profile.get("b5_rubric_id") == "rubric.macro_investigator_qa", (
            "Profile must reference rubric.macro_investigator_qa"
        )

    def test_prompt_file_contains_citation_grammar(self):
        """Bug 3: system prompt must instruct citation emission."""
        prompt_path = PROMPTS_DIR / "macro_investigator.md"
        assert prompt_path.exists(), f"Prompt file not found at {prompt_path}"
        content = prompt_path.read_text()
        assert "[ref:" in content, (
            "Prompt must contain [ref:...] citation grammar instruction (Bug 3 fix)"
        )
        assert "citations" in content, (
            "Prompt must reference the citations[] output field"
        )

    def test_prompt_file_contains_tool_use_mandate(self):
        """Bug 3: system prompt must mandate tool use before answering."""
        prompt_path = PROMPTS_DIR / "macro_investigator.md"
        content = prompt_path.read_text()
        # Should mention calling tools, not relying on training memory
        assert "tool" in content.lower(), (
            "Prompt must mandate tool use (Bug 3 fix)"
        )
        assert "training memory" in content.lower() or "training-memory" in content.lower(), (
            "Prompt must explicitly forbid relying on training memory alone"
        )

    def test_prompt_file_has_json_envelope_schema(self):
        """Bug 3: system prompt must instruct structured JSON output."""
        prompt_path = PROMPTS_DIR / "macro_investigator.md"
        content = prompt_path.read_text()
        assert '"answer"' in content, (
            "Prompt must show the answer field in the output schema"
        )
        assert '"citations"' in content, (
            "Prompt must show the citations field in the output schema"
        )
        assert '"degraded"' in content, (
            "Prompt must show the degraded field in the output schema"
        )

    def test_registry_entry_still_exists(self):
        """Regression: capability-registry entry must NOT be deleted."""
        registry_path = (
            VM107_ROOT
            / "registry"
            / "agent_profile"
            / "vm107.macro_investigator.yaml"
        )
        assert registry_path.exists(), (
            "Phase 47.6 capability-registry entry must remain untouched. "
            "The runtime profile is separate from it."
        )


# ---------------------------------------------------------------------------
# Bug 1 — response_self_check slot wired in agent.py
# ---------------------------------------------------------------------------


class TestResponseSelfCheckSlot:
    """Bug 1 fix: agent.py must call extension.call_extensions_async('response_self_check', ...)."""

    def test_response_self_check_slot_in_agent_source(self):
        """Assert 'response_self_check' string appears in agent.py."""
        source = AGENT_PY.read_text()
        assert "response_self_check" in source, (
            "Bug 1: agent.py must call extension.call_extensions_async('response_self_check', ...). "
            "Without this, B5 and citation-collection extensions never fire."
        )

    def test_response_self_check_fires_before_reasoning_stream_end(self):
        """Assert response_self_check is inserted BEFORE reasoning_stream_end in source order."""
        source = AGENT_PY.read_text()
        idx_self_check = source.find("response_self_check")
        idx_reasoning_end = source.find("reasoning_stream_end")
        assert idx_self_check != -1, "response_self_check not found in agent.py"
        assert idx_reasoning_end != -1, "reasoning_stream_end not found in agent.py"
        assert idx_self_check < idx_reasoning_end, (
            "response_self_check must appear BEFORE reasoning_stream_end in agent.py "
            "so B5 sets confidence_self_report before the persist hook reads it."
        )

    def test_response_self_check_extension_file_exists(self):
        """Assert the B5 extension file exists in the response_self_check slot directory."""
        ext_path = (
            VM107_ROOT
            / "extensions"
            / "python"
            / "response_self_check"
            / "_10_b5_self_check.py"
        )
        assert ext_path.exists(), (
            f"B5 extension not found at {ext_path}. "
            "The extension must exist for the slot to do anything."
        )


# ---------------------------------------------------------------------------
# Bug 2 — ApiMessage returns structured envelope for macro_investigator
# ---------------------------------------------------------------------------


class TestApiMessageEnvelope:
    """Bug 2 fix: when agent_profile='vm107.macro_investigator', ApiMessage must
    return {response_id, answer, citations, b5_result, degraded,
    blocking_contradiction_refusal, truncated_at} instead of {context_id, response}.
    """

    def test_api_message_source_contains_macro_investigator_branch(self):
        """Assert api_message.py has a branch keyed on 'vm107.macro_investigator'."""
        source = API_MESSAGE_PY.read_text()
        assert "vm107.macro_investigator" in source, (
            "Bug 2: api_message.py must branch on agent_profile == 'vm107.macro_investigator' "
            "to return the structured AskResponse envelope."
        )

    def test_api_message_source_returns_answer_field(self):
        """Assert api_message.py assembles an 'answer' key in the return dict."""
        source = API_MESSAGE_PY.read_text()
        assert '"answer"' in source, (
            "Bug 2: api_message.py macro_investigator branch must return an 'answer' key."
        )

    def test_api_message_source_returns_citations_field(self):
        source = API_MESSAGE_PY.read_text()
        assert '"citations"' in source, (
            "Bug 2: api_message.py macro_investigator branch must return a 'citations' key."
        )

    def test_api_message_source_returns_b5_result_field(self):
        source = API_MESSAGE_PY.read_text()
        assert '"b5_result"' in source, (
            "Bug 2: api_message.py macro_investigator branch must return a 'b5_result' key."
        )

    def test_api_message_source_returns_degraded_field(self):
        source = API_MESSAGE_PY.read_text()
        assert '"degraded"' in source, (
            "Bug 2: api_message.py macro_investigator branch must return a 'degraded' key."
        )

    def test_api_message_preserves_default_response_field(self):
        """Non-investigator traffic must still get {context_id, response} shape."""
        source = API_MESSAGE_PY.read_text()
        assert '"response"' in source, (
            "Bug 2: api_message.py must preserve the original {context_id, response} "
            "return path for non-investigator profiles (backward compat)."
        )

    def test_api_message_envelope_unit(self):
        """Unit test: mock context + agent to assert envelope shape.

        This test patches AgentContext, UserMessage, and initialize_agent so
        the real Django/async stack is never touched. It validates that the
        macro_investigator branch assembles and returns the correct shape.
        """
        import asyncio
        import sys
        import types
        from unittest.mock import AsyncMock, MagicMock, patch

        # ---------------------------------------------------------------------------
        # Minimal stubs for modules that api_message.py imports at module level.
        # We inject these before importing api_message to avoid ImportError.
        # ---------------------------------------------------------------------------
        stubs: dict[str, types.ModuleType] = {}

        def _make_stub(name: str) -> types.ModuleType:
            mod = types.ModuleType(name)
            stubs[name] = mod
            return mod

        # agent module stub
        agent_mod = _make_stub("agent")
        agent_mod.AgentContext = MagicMock()
        agent_mod.UserMessage = MagicMock()
        agent_mod.AgentContextType = MagicMock()

        # helpers stubs
        helpers_mod = _make_stub("helpers")
        helpers_api_mod = _make_stub("helpers.api")

        class _FakeHandler:
            pass

        helpers_api_mod.ApiHandler = _FakeHandler
        helpers_api_mod.Request = MagicMock()
        helpers_api_mod.Response = MagicMock(side_effect=lambda body, status=200, mimetype=None: {"_body": body, "_status": status})
        helpers_files_mod = _make_stub("helpers.files")
        helpers_files_mod.get_abs_path = lambda p: f"/tmp/{p}"
        helpers_projects_mod = _make_stub("helpers.projects")
        helpers_projects_mod.CONTEXT_DATA_KEY_PROJECT = "project"
        helpers_projects_mod.activate_project = MagicMock()
        helpers_print_mod = _make_stub("helpers.print_style")
        helpers_print_mod.PrintStyle = MagicMock()
        helpers_security_mod = _make_stub("helpers.security")
        helpers_security_mod.safe_filename = lambda f: f
        init_mod = _make_stub("initialize")
        init_mod.initialize_agent = MagicMock(return_value=MagicMock())

        # Populate sub-stubs so 'from helpers.X import Y' works
        helpers_mod.api = helpers_api_mod
        helpers_mod.files = helpers_files_mod
        helpers_mod.projects = helpers_projects_mod
        helpers_mod.print_style = helpers_print_mod
        helpers_mod.security = helpers_security_mod

        with patch.dict(sys.modules, {
            "agent": agent_mod,
            "helpers": helpers_mod,
            "helpers.api": helpers_api_mod,
            "helpers.files": helpers_files_mod,
            "helpers.projects": helpers_projects_mod,
            "helpers.print_style": helpers_print_mod,
            "helpers.security": helpers_security_mod,
            "initialize": init_mod,
        }):
            # Import freshly with our stubs
            if "api.api_message" in sys.modules:
                del sys.modules["api.api_message"]

            import importlib
            spec = importlib.util.spec_from_file_location(
                "api.api_message", API_MESSAGE_PY
            )
            api_msg_module = importlib.util.module_from_spec(spec)
            # Patch threading.Lock inside module space
            spec.loader.exec_module(api_msg_module)

        ApiMessage = api_msg_module.ApiMessage

        # Build a mock agent0 mimicking the investigator profile
        agent0 = MagicMock()
        agent0.config = MagicMock()
        agent0.config.profile = "vm107.macro_investigator"
        agent0.last_response = (
            "CPI came in at 3.4% [ref:release:CPIAUCSL-2026-06-10], above consensus."
        )

        _data = {
            "citations": [{"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4%"}],
            "b5_result": {"total": 0.85, "recommendation": "accept", "per_check": {}},
            "b5_degraded": None,
            "blocking_contradiction_refusal": None,
            "last_b1_artifact_id": "artifact-uuid-001",
            "truncated_at": None,
        }
        agent0.get_data.side_effect = lambda key, *args: _data.get(key, args[0] if args else None)

        # Mock context
        context = MagicMock()
        context.agent0 = agent0
        context.id = "ctx-test-001"
        context.get_data.return_value = None
        context.log = MagicMock()
        context.communicate.return_value = MagicMock(
            result=AsyncMock(return_value="raw_model_output")
        )

        # Patch AgentContext.use to return the mocked context
        agent_mod.AgentContext.use.return_value = context

        # Call ApiMessage.process
        handler = ApiMessage()
        handler._cleanup_expired_chats = MagicMock()

        input_data = {
            "context_id": "ctx-test-001",
            "message": "Explain this CPI release",
            "agent_profile": "vm107.macro_investigator",
        }

        result = asyncio.get_event_loop().run_until_complete(
            handler.process(input_data, MagicMock())
        )

        # Assert structured envelope shape
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "answer" in result, f"Missing 'answer' key. Got keys: {list(result.keys())}"
        assert "citations" in result, f"Missing 'citations' key. Got keys: {list(result.keys())}"
        assert "b5_result" in result, f"Missing 'b5_result' key. Got keys: {list(result.keys())}"
        assert "degraded" in result, f"Missing 'degraded' key."
        assert "blocking_contradiction_refusal" in result, "Missing 'blocking_contradiction_refusal' key."
        assert "response_id" in result, "Missing 'response_id' key."
        # Must NOT contain raw 'response' field (which would be the bug)
        assert "response" not in result, (
            "BUG 2 REGRESSION: 'response' field present — envelope not assembled. "
            f"Got keys: {list(result.keys())}"
        )
        # Phase 89.1 Plan 01 follow-up fix (2026-06-22): citation schema harmonization.
        # The mock data used citation_id/source/snippet (B1 CitationRef shape).
        # After harmonize_citations() the returned dicts MUST use ref_id/kind/label
        # so VM100 _parse_ask_response() can call Citation(**c) without TypeError.
        citations_out = result["citations"]
        assert len(citations_out) >= 1, "Expected at least one citation in result"
        for c in citations_out:
            assert "ref_id" in c, (
                f"citation missing 'ref_id' — harmonizer did not run. Got: {c!r}"
            )
            assert "citation_id" not in c, (
                f"citation still has 'citation_id' — harmonizer did not convert B1 shape. Got: {c!r}"
            )
            assert "kind" in c, (
                f"citation missing 'kind' — harmonizer did not run. Got: {c!r}"
            )
