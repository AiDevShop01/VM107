import base64
import os
import uuid
from datetime import datetime, timedelta
from agent import AgentContext, UserMessage, AgentContextType
from helpers.api import ApiHandler, Request, Response
from helpers import files, projects
from helpers.print_style import PrintStyle
from helpers.projects import activate_project
from helpers.security import safe_filename
from helpers.macro_envelope_parser import parse_macro_envelope
from helpers.profile_aware_dispatch import load_profile_into_agent
from initialize import initialize_agent
import threading


class ApiMessage(ApiHandler):
    # Track chat lifetimes for cleanup
    _chat_lifetimes = {}
    _cleanup_lock = threading.Lock()

    @classmethod
    def requires_auth(cls) -> bool:
        return False  # No web auth required

    @classmethod
    def requires_csrf(cls) -> bool:
        return False  # No CSRF required

    @classmethod
    def requires_api_key(cls) -> bool:
        return True  # Require API key

    async def process(self, input: dict, request: Request) -> dict | Response:
        # Extract parameters
        context_id = input.get("context_id", "")
        message = input.get("message", "")
        attachments = input.get("attachments", [])
        lifetime_hours = input.get("lifetime_hours", 24)  # Default 24 hours
        project_name = input.get("project_name", None)
        agent_profile = input.get("agent_profile", None)
        
        # Set an agent if profile provided
        override_settings = {}
        if agent_profile:
            override_settings["agent_profile"] = agent_profile

        if not message:
            return Response('{"error": "Message is required"}', status=400, mimetype="application/json")

        # Handle attachments (base64 encoded)
        attachment_paths = []
        if attachments:
            upload_folder_int = "/a0/usr/uploads"
            upload_folder_ext = files.get_abs_path("usr/uploads")
            os.makedirs(upload_folder_ext, exist_ok=True)

            for attachment in attachments:
                if not isinstance(attachment, dict) or "filename" not in attachment or "base64" not in attachment:
                    continue

                try:
                    filename = safe_filename(attachment["filename"])
                    if not filename:
                        raise ValueError("Invalid filename")

                    # Decode base64 content
                    file_content = base64.b64decode(attachment["base64"])

                    # Save to temp file
                    save_path = os.path.join(upload_folder_ext, filename)
                    with open(save_path, "wb") as f:
                        f.write(file_content)

                    attachment_paths.append(os.path.join(upload_folder_int, filename))
                except Exception as e:
                    PrintStyle.error(f"Failed to process attachment {attachment.get('filename', 'unknown')}: {e}")
                    continue

        # Get or create context
        if context_id:
            context = AgentContext.use(context_id)
            if not context:
                return Response('{"error": "Context not found"}', status=404, mimetype="application/json")

            # Validation: if agent profile is provided, it must match the exising
            if agent_profile and context.agent0.config.profile != agent_profile:
                return Response('{"error": "Cannot override agent profile on existing context"}', status=400, mimetype="application/json")
            

            # Validation: if project is provided but context already has different project
            existing_project = context.get_data(projects.CONTEXT_DATA_KEY_PROJECT)
            if project_name and existing_project and existing_project != project_name:
                return Response('{"error": "Project can only be set on first message"}', status=400, mimetype="application/json")
        else:
            config = initialize_agent(override_settings=override_settings)
            context = AgentContext(config=config, type=AgentContextType.USER)
            AgentContext.use(context.id)
            context_id = context.id
            # Activate project if provided
            if project_name:
                try:
                    activate_project(context_id, project_name)
                except Exception as e:
                    # Handle project or context errors more gracefully
                    error_msg = str(e)
                    PrintStyle.error(f"Failed to activate project '{project_name}' for context '{context_id}': {error_msg}")
                    return Response(
                        f'{{"error": "Failed to activate project \\"{project_name}\\""}}',
                        status=500,
                        mimetype="application/json",
                    )

            # Activate project if provided
            if project_name:
                try:
                    projects.activate_project(context_id, project_name)
                except Exception as e:
                    return Response(f'{{"error": "Failed to activate project: {str(e)}"}}', status=400, mimetype="application/json")

        # Update chat lifetime
        with self._cleanup_lock:
            self._chat_lifetimes[context_id] = datetime.now() + timedelta(hours=lifetime_hours)

        # Phase 89.1 Plan 04 — profile-aware dispatch middleware (Path B).
        # Extracted from the former inline if-branch via 89.1-04-DISPATCH-DECISION-LOG.md.
        # Works for ANY registry/agent_profile/*.yaml profile — no hardcoded profile ids.
        # For async background agents (macro_release_analyst, etc.) the Phase 85.1
        # task_scheduler owns its own profile loading; this middleware is for the
        # synchronous user-Q&A path only.
        if agent_profile:
            try:
                load_profile_into_agent(context.agent0, agent_profile)
            except FileNotFoundError:
                PrintStyle.error(
                    f"api_message: profile '{agent_profile}' not found in registry; "
                    f"running in legacy (no-profile) mode"
                )
            except Exception as _exc:
                PrintStyle.error(
                    f"api_message: profile load failed for '{agent_profile}': {_exc}"
                )

        # Process message
        try:
            # Log the message
            attachment_filenames = [os.path.basename(path) for path in attachment_paths] if attachment_paths else []

            PrintStyle(
                background_color="#6C3483", font_color="white", bold=True, padding=True
            ).print("External API message:")
            PrintStyle(font_color="white", padding=False).print(f"> {message}")
            if attachment_filenames:
                PrintStyle(font_color="white", padding=False).print("Attachments:")
                for filename in attachment_filenames:
                    PrintStyle(font_color="white", padding=False).print(f"- {filename}")

            # Add user message to chat history so it's visible in the UI
            msg_id = str(uuid.uuid4())
            context.log.log(
                type="user",
                heading="",
                content=message,
                kvps={"attachments": attachment_filenames},
                id=msg_id,
            )

            # Send message to agent
            # Phase 89.1: attach any profile system prompt via system_message so
            # citation/tool-use instructions reach the LLM. The middleware stores
            # the prompt under "_system_prompt" (generic key, not profile-specific).
            _sys_msgs: list[str] = []
            _sys_prompt = context.agent0.get_data("_system_prompt")
            if _sys_prompt:
                _sys_msgs = [_sys_prompt]
            task = context.communicate(UserMessage(message=message, attachments=attachment_paths, id=msg_id, system_message=_sys_msgs))
            result = await task.result()

            # Clean up expired chats
            self._cleanup_expired_chats()

            # Phase 89 Plan 01 wiring fix (Bug 2) — return AskResponse-compatible
            # envelope for macro_investigator so VM100 parser gets structured fields
            # (answer, citations, b5_result, degraded, blocking_contradiction_refusal)
            # instead of the raw {context_id, response} shape, which VM100 was dumping
            # verbatim into the answer field.
            _profile = agent_profile or getattr(
                getattr(context, "agent0", None),
                "config",
                type("_C", (), {"profile": ""})(),
            ).profile or ""
            if _profile == "vm107.macro_investigator":
                import uuid as _uuid

                agent0 = context.agent0
                # `result` is the monologue return value (the final response text).
                # agent0.last_response does NOT exist on Agent — it lives on LoopData.
                # Use `result` directly; parse_macro_envelope extracts structured
                # fields if the model emitted the standard "prose + ```json fence"
                # shape (Phase 89.1 Plan 01 — REQ-89-9.1 fence-block extraction fix).
                answer_text = (result or "").strip()
                citations = agent0.get_data("citations") or []
                b5_result = agent0.get_data("b5_result")
                degraded = bool(agent0.get_data("b5_degraded") or False)
                blocking = bool(agent0.get_data("blocking_contradiction_refusal") or False)
                truncated_at = agent0.get_data("truncated_at")

                # Priority rule: agent0.get_data() slots (set by extensions during
                # the loop) win OVER envelope values (model self-reports may lie).
                # Envelope only fills slots that are still empty/falsy after
                # agent-data extraction.
                answer_prose, envelope = parse_macro_envelope(answer_text)
                if envelope:
                    # Use the clean prose (fence stripped) as the answer.
                    # Fall back to envelope["answer"] if prose extraction left empty
                    # (bare-JSON backward-compat path).
                    answer_text = answer_prose or envelope.get("answer", answer_text)
                    if not citations:
                        citations = envelope.get("citations") or []
                    if b5_result is None:
                        b5_result = envelope.get("b5_result")
                    if not degraded:
                        degraded = bool(envelope.get("degraded", False))
                    if not blocking:
                        blocking = bool(envelope.get("blocking_contradiction_refusal", False))
                    if truncated_at is None:
                        truncated_at = envelope.get("truncated_at")

                return {
                    "context_id": context_id,
                    "response_id": (
                        agent0.get_data("last_b1_artifact_id") or str(_uuid.uuid4())
                    ),
                    "answer": answer_text,
                    "citations": citations,
                    "b5_result": b5_result,
                    "degraded": degraded,
                    "blocking_contradiction_refusal": blocking,
                    "truncated_at": truncated_at,
                }

            # Default (non-investigator) behavior preserved — backward compat
            return {
                "context_id": context_id,
                "response": result
            }

        except Exception as e:
            PrintStyle.error(f"External API error: {e}")
            return Response(f'{{"error": "{str(e)}"}}', status=500, mimetype="application/json")

    @classmethod
    def _cleanup_expired_chats(cls):
        """Clean up expired chats"""
        with cls._cleanup_lock:
            now = datetime.now()
            expired_contexts = [
                context_id for context_id, expiry in cls._chat_lifetimes.items()
                if now > expiry
            ]

            for context_id in expired_contexts:
                try:
                    context = AgentContext.get(context_id)
                    if context:
                        context.reset()
                        AgentContext.remove(context_id)
                    del cls._chat_lifetimes[context_id]
                    PrintStyle().print(f"Cleaned up expired chat: {context_id}")
                except Exception as e:
                    PrintStyle.error(f"Failed to cleanup chat {context_id}: {e}")
