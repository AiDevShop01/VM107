from abc import abstractmethod
import base64
import json
import logging
import os
import threading
from functools import wraps
from pathlib import Path
from typing import Union, Dict, Any
from flask import (
    Request,
    Response,
    jsonify,
    Flask,
    session,
    request,
    send_file,
    redirect,
    url_for,
)
from werkzeug.wrappers.response import Response as BaseResponse
from agent import AgentContext
from helpers.print_style import PrintStyle
from helpers.errors import format_error
from helpers import files, cache

_jwt_audit_log = logging.getLogger("vm107.api.jwt_audit")
# Force INFO level on the JWT audit logger so VM107's container log shows
# it. Otherwise the default root logger config may swallow INFO emits and
# the audit trail goes silent. Phase 73-followup audit requirement.
if not _jwt_audit_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _jwt_audit_log.addHandler(_h)
    _jwt_audit_log.setLevel(logging.INFO)
    _jwt_audit_log.propagate = False

ThreadLockType = Union[threading.Lock, threading.RLock]

CACHE_AREA = "api_handlers(api)"
# cache.toggle_area(CACHE_AREA, False)  # cache off for now

Input = dict
Output = Union[Dict[str, Any], Response]


class ApiHandler:
    def __init__(self, app: Flask, thread_lock: ThreadLockType):
        self.app = app
        self.thread_lock = thread_lock

    @classmethod
    def requires_loopback(cls) -> bool:
        return False

    @classmethod
    def requires_api_key(cls) -> bool:
        return False

    @classmethod
    def requires_auth(cls) -> bool:
        return True

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return cls.requires_auth()

    @abstractmethod
    async def process(self, input: Input, request: Request) -> Output:
        pass

    async def handle_request(self, request: Request) -> Response:
        try:
            # input data from request based on type
            input_data: Input = {}
            if request.is_json:
                try:
                    if request.data:  # Check if there's any data
                        input_data = request.get_json()
                    # If empty or not valid JSON, use empty dict
                except Exception as e:
                    # Just log the error and continue with empty input
                    PrintStyle().print(f"Error parsing JSON: {str(e)}")
                    input_data = {}
            else:
                # input_data = {"data": request.get_data(as_text=True)}
                input_data = {}

            # process via handler
            output = await self.process(input_data, request)

            # return output based on type
            if isinstance(output, Response):
                return output
            else:
                response_json = json.dumps(output)
                return Response(
                    response=response_json, status=200, mimetype="application/json"
                )

            # return exceptions with 500
        except Exception as e:
            error = format_error(e)
            PrintStyle.error(f"API error: {error}")
            return Response(response=error, status=500, mimetype="text/plain")

    # get context to run agent zero in
    def use_context(self, ctxid: str, create_if_not_exists: bool = True):
        from helpers.context_utils import use_context as _use_context
        return _use_context(self.thread_lock, ctxid, create_if_not_exists)


from helpers.network import is_loopback_address


def _resolve_valid_api_key() -> str:
    """Resolve the valid VM107 service API key.

    Phase 73-followup VM100↔VM107 service-auth lock:
      1. `VM107_INTERNAL_TOKEN` env var takes precedence (env-driven config
         per project lock — service-to-service tokens live in env, not
         settings.json, so they can rotate without UI/disk changes).
      2. Fall back to the legacy `mcp_server_token` settings.json value
         when the env var is unset (back-compat for the existing MCP
         server token path).

    Returns the resolved token string (may be empty if neither source
    populated it — that case is treated as "no API key configured" and
    requests with `X-API-KEY` will be rejected as invalid).
    """
    env_token = os.environ.get("VM107_INTERNAL_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        from helpers.settings import get_settings
        return get_settings().get("mcp_server_token", "") or ""
    except Exception:  # pragma: no cover — defensive; settings init may fail early
        return ""


def _audit_log_jwt_if_present() -> None:
    """Audit-only JWT decode: log user_id/account_id claims if Bearer present.

    Phase 73-followup VM100↔VM107 combined-auth-approach (A+B):
      - X-API-KEY (handled by @requires_api_key) is the trust gate.
      - The Authorization: Bearer <jwt> header is OPTIONAL and is decoded
        WITHOUT signature verification purely so VM107 has a user-identity
        audit trail. NEVER use these claims for authz — the JWT is not
        trusted (VM107 does not share the JWT signing key with VM100).

    Defensive: malformed JWT, missing header, decode errors — all swallowed.
    Never raise from the audit path; an audit-logger bug must not break the
    request.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return
        token = auth_header[len("Bearer "):].strip()
        if not token:
            return
        parts = token.split(".")
        if len(parts) < 2:
            return
        # JWT payload is the 2nd segment, base64url-encoded JSON.
        payload_b64 = parts[1]
        # base64 requires padding length be a multiple of 4.
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        claims = json.loads(payload_bytes.decode("utf-8"))
        # Pluck the two claims VM100's JWT carries (Phase 72 deploy-fix
        # surfaced these as `user_id` + `account_id` in mission_control views).
        user_id = claims.get("user_id")
        account_id = claims.get("account_id")
        _jwt_audit_log.info(
            "vm107.api.jwt_audit path=%s user_id=%s account_id=%s",
            request.path,
            user_id,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — audit MUST NOT break requests
        # Log + swallow; never raise.
        _jwt_audit_log.warning(
            "vm107.api.jwt_audit_decode_failed: %s(%s)",
            type(exc).__name__,
            exc,
        )


def requires_api_key(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        valid_api_key = _resolve_valid_api_key()

        if api_key := request.headers.get("X-API-KEY"):
            if not valid_api_key or api_key != valid_api_key:
                return Response("Invalid API key", 401)
        elif request.json and request.json.get("api_key"):
            api_key = request.json.get("api_key")
            if not valid_api_key or api_key != valid_api_key:
                return Response("Invalid API key", 401)
        else:
            return Response("API key required", 401)

        # Phase 73-followup — audit-only JWT decode (NOT a trust gate).
        _audit_log_jwt_if_present()

        return await f(*args, **kwargs)

    return decorated


def requires_loopback(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        if not is_loopback_address(str(request.remote_addr)):
            return Response("Access denied.", 403, {})
        return await f(*args, **kwargs)

    return decorated


def requires_auth(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        from helpers import login

        user_pass_hash = login.get_credentials_hash()
        if not user_pass_hash:
            return await f(*args, **kwargs)
        if session.get("authentication") != user_pass_hash:
            return redirect(url_for("login_handler"))
        return await f(*args, **kwargs)

    return decorated


def csrf_protect(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        from helpers import runtime

        token = session.get("csrf_token")
        header = request.headers.get("X-CSRF-Token")
        cookie = request.cookies.get("csrf_token_" + runtime.get_runtime_id())
        sent = header or cookie
        if not token or not sent or token != sent:
            return Response("CSRF token missing or invalid", 403)
        return await f(*args, **kwargs)

    return decorated


def register_api_route(app: Flask, lock: ThreadLockType) -> None:
    from helpers.modules import load_classes_from_file
    from helpers import plugins

    async def _dispatch(path: str) -> BaseResponse:
        # Return cached wrapped handler if available
        cached = cache.get(CACHE_AREA, path)
        if cached is not None:
            return await cached()

        # Resolve file path for the handler
        # Try built-in api folder first, then plugin api folders
        handler_cls: type[ApiHandler] | None = None

        # Check built-in python/api/<path>.py
        builtin_file = files.get_abs_path(f"api/{path}.py")
        if files.is_in_dir(builtin_file, files.get_abs_path("api")) and files.exists(
            builtin_file
        ):
            classes = load_classes_from_file(builtin_file, ApiHandler)
            if classes:
                handler_cls = classes[0]

        # Check plugin api folders: path format plugins/<plugin_name>/<handler>
        if handler_cls is None and path.startswith("plugins/"):
            parts = path.split("/", 2)
            if len(parts) == 3:
                _, plugin_name, handler_name = parts
                plugin_dir = plugins.find_plugin_dir(plugin_name)
                if plugin_dir:
                    plugin_file = Path(plugin_dir) / "api" / f"{handler_name}.py"
                    if plugin_file.is_file():
                        classes = load_classes_from_file(str(plugin_file), ApiHandler)
                        if classes:
                            handler_cls = classes[0]

        if handler_cls is None:
            return Response(f"API endpoint not found: {path}", 404)

        # Check method is allowed
        if request.method not in handler_cls.get_methods():
            return Response(f"Method {request.method} not allowed for: {path}", 405)

        # Build handler call, wrapping with security decorators as required
        async def call_handler() -> BaseResponse:
            instance = handler_cls(app, lock)
            return await instance.handle_request(request=request)

        handler_fn = call_handler
        if handler_cls.requires_csrf():
            handler_fn = csrf_protect(handler_fn)
        if handler_cls.requires_api_key():
            handler_fn = requires_api_key(handler_fn)
        if handler_cls.requires_auth():
            handler_fn = requires_auth(handler_fn)
        if handler_cls.requires_loopback():
            handler_fn = requires_loopback(handler_fn)

        cache.add(CACHE_AREA, path, handler_fn)
        return await handler_fn()

    app.add_url_rule(
        "/api/<path:path>",
        "api_dispatch",
        _dispatch,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )


def register_watchdogs():
    from helpers import watchdog
    from helpers.ws import CACHE_AREA as WS_CACHE_AREA


    def on_api_change(items: list[watchdog.WatchItem]):
        PrintStyle.debug("API endpoint watchdog triggered:", items)
        cache.clear(CACHE_AREA)
        cache.clear(WS_CACHE_AREA)

    watchdog.add_watchdog(
        "api_handlers",
        roots=[
            files.get_abs_path(files.API_DIR),
            files.get_abs_path(files.USER_DIR, files.API_DIR),
        ],
        patterns=["*.py"],
        handler=on_api_change,
    )
