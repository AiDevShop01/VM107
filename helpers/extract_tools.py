
from .dirty_json import DirtyJson
import regex, re
from helpers.modules import load_classes_from_file, load_classes_from_folder # keep here for backwards compatibility
from typing import Any


def _find_tool_request_object(content: str) -> "dict[str, Any] | None":
    """Scan *content* for a top-level JSON object that has ``tool_name`` or
    ``tool`` as a top-level key with a non-empty string value.

    Returns the first such object found, or ``None`` if none exist.

    Design notes:
    - Uses ``DirtyJson`` per candidate ``{`` position so it respects nested
      braces correctly (no naïve first-``{``-to-last-``}`` smashing).
    - Only matches when the key's value is a non-empty string — filters junk
      like ``{"tool_name": null}`` that DeepSeek sometimes embeds in prose.
    - Falls through cleanly (returns ``None``) if no tool-request-shaped
      object is found so the existing fallback path in ``json_parse_dirty``
      takes over.
    - Defensive against malformed input via try/except around every DirtyJson
      call to avoid infinite loops or crashes on weird LLM output.
    """
    if not content:
        return None
    pos = 0
    while True:
        start = content.find("{", pos)
        if start == -1:
            return None
        parser = DirtyJson()
        try:
            parser.parse(content[start:])
        except Exception:
            pos = start + 1
            continue
        if parser.completed:
            end = start + parser.index
            try:
                obj = DirtyJson.parse_string(content[start:end])
                if isinstance(obj, dict):
                    tool_name_val = obj.get("tool_name") or obj.get("tool")
                    if isinstance(tool_name_val, str) and tool_name_val:
                        return obj
            except Exception:
                pass
            # Slide forward past this object and keep searching
            pos = start + max(parser.index, 1)
        else:
            # Parser couldn't complete a JSON object from this position
            pos = start + 1


def json_parse_dirty(json: str) -> "dict[str, Any] | None":
    if not json or not isinstance(json, str):
        return None

    # BUG-19: Prefer a JSON object that has tool_name/tool at top level.
    # This prevents embedded scoring JSON ({"score": null, ...}) from being
    # mistaken for a tool call when a real tool call follows in the same content.
    tool_obj = _find_tool_request_object(json.strip())
    if tool_obj is not None:
        return tool_obj

    # Existing fallback: grab outer {...} naively, parse, return if dict.
    ext_json = extract_json_object_string(json.strip())
    if ext_json:
        try:
            data = DirtyJson.parse_string(ext_json)
            if isinstance(data, dict):
                return data
        except Exception:
            # If parsing fails, return None instead of crashing
            return None
    return None

def extract_json_root_string(content: str) -> str | None:
    if not content or not isinstance(content, str):
        return None

    start = content.find("{")
    if start == -1:
        return None
    first_array = content.find("[")
    if first_array != -1 and first_array < start:
        return None

    parser = DirtyJson()
    try:
        parser.parse(content[start:])
    except Exception:
        return None

    if not parser.completed:
        return None

    return content[start : start + parser.index]


def extract_json_object_string(content):
    start = content.find("{")
    if start == -1:
        return ""

    # Find the first '{'
    end = content.rfind("}")
    if end == -1:
        # If there's no closing '}', return from start to the end
        return content[start:]
    else:
        # If there's a closing '}', return the substring from start to end
        return content[start : end + 1]


def extract_json_string(content):
    # Regular expression pattern to match a JSON object
    pattern = r'\{(?:[^{}]|(?R))*\}|\[(?:[^\[\]]|(?R))*\]|"(?:\\.|[^"\\])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'

    # Search for the pattern in the content
    match = regex.search(pattern, content)

    if match:
        # Return the matched JSON string
        return match.group(0)
    else:
        return ""


def fix_json_string(json_string):
    # Function to replace unescaped line breaks within JSON string values
    def replace_unescaped_newlines(match):
        return match.group(0).replace("\n", "\\n")

    # Use regex to find string values and apply the replacement function
    fixed_string = re.sub(
        r'(?<=: ")(.*?)(?=")', replace_unescaped_newlines, json_string, flags=re.DOTALL
    )
    return fixed_string


