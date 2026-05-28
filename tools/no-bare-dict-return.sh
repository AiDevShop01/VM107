#!/usr/bin/env bash
# VM107/tools/no-bare-dict-return.sh
# Phase 70.5 REQ-70.5-8 — no bare dict returns from dispatch-path tools.
#
# A dispatch-path return is the final return value from a tool's public
# run / run_async / execute method (or a top-level callable). Internal
# helper functions that compute intermediate dicts are NOT dispatch-path.
#
# Acceptable patterns (NOT flagged):
#   - return {  inside def _*  (private helper/method, not dispatch path)
#   - return {  in helper-file exclusion list (response.py / scheduler.py / etc.)
#   - return {  on a line that contains "# PROVENANCE-EXEMPT"
#   - return {  inside a function/method whose def line starts with "def _"
#     (detected via AWK enclosing-function scan)
#
# Everything else is a RED — exit !=0 with file:line:context.
#
# Usage:
#   bash VM107/tools/no-bare-dict-return.sh          # scan from repo root
#   bash VM107/tools/no-bare-dict-return.sh <dir>    # scan specific dir
#
# Exit codes:
#   0  — green: no violations found
#   1  — red:   one or more violations; offending file:line printed to stdout
#
# DESIGN: two-pass AWK approach
#   Pass 1: find all "return {" lines
#   Pass 2: for each hit, check the enclosing function name by scanning
#           backwards for the most recent "def " line in the file
#
# AWK tracks the last seen def-name so it can classify each return-{ line.
# Helper files are excluded via --exclude flags before AWK processing.

set -uo pipefail

TOOLS_DIR="${1:-VM107/tools}"

# ---------------------------------------------------------------------------
# Helper-file exclusion list — these files are infrastructure/helpers, NOT
# dispatch-path tool modules (per Phase 70.5 RESEARCH "Quantified Tool Inventory")
# ---------------------------------------------------------------------------
EXCLUDE_FILES=(
    "response.py"
    "scheduler.py"
    "wait.py"
    "search_engine.py"
    "unknown.py"
)

# Build --exclude args for grep
GREP_EXCLUDES=()
for f in "${EXCLUDE_FILES[@]}"; do
    GREP_EXCLUDES+=("--exclude=${f}")
done

# ---------------------------------------------------------------------------
# Collect candidate files (all .py under TOOLS_DIR except excluded names)
# ---------------------------------------------------------------------------
CANDIDATE_FILES=()
while IFS= read -r -d '' f; do
    fname=$(basename "$f")
    skip=false
    for ex in "${EXCLUDE_FILES[@]}"; do
        if [[ "$fname" == "$ex" ]]; then
            skip=true
            break
        fi
    done
    if [[ "$skip" == false ]]; then
        CANDIDATE_FILES+=("$f")
    fi
done < <(find "$TOOLS_DIR" -name "*.py" -print0 2>/dev/null)

if [[ ${#CANDIDATE_FILES[@]} -eq 0 ]]; then
    echo "REQ-70.5-8 source-grep gate: no .py files found under ${TOOLS_DIR}"
    exit 0
fi

# ---------------------------------------------------------------------------
# AWK two-pass scan:
#   For each file, track the most recently seen "def " line.
#   When "return {" is found:
#     - Skip if line contains "PROVENANCE-EXEMPT"
#     - Skip if enclosing function name starts with "_"
#     - Otherwise: record violation
# ---------------------------------------------------------------------------
VIOLATIONS=$(awk '
BEGIN {
    current_func = ""
    violations = ""
}
FNR == 1 {
    # Reset per-file state
    current_func = ""
}
/^[[:space:]]*(async[[:space:]]+)?def [[:space:]]*/ {
    # Extract function/method name from "def name(" or "async def name("
    line = $0
    # Strip leading whitespace
    sub(/^[[:space:]]+/, "", line)
    # Strip "async "
    sub(/^async[[:space:]]+/, "", line)
    # Now line starts with "def "
    sub(/^def[[:space:]]+/, "", line)
    # Extract name (up to first "(")
    n = index(line, "(")
    if (n > 0) {
        current_func = substr(line, 1, n - 1)
    } else {
        current_func = line
    }
}
/^[[:space:]]*return[[:space:]]+\{/ {
    # Check for PROVENANCE-EXEMPT on same line
    if ($0 ~ /PROVENANCE-EXEMPT/) next
    # Check if enclosing function starts with "_" (private helper)
    if (current_func ~ /^_/) next
    # Violation: dispatch-path bare dict return
    violations = violations FILENAME ":" FNR ": " $0 "\n"
}
END {
    printf "%s", violations
}
' "${CANDIDATE_FILES[@]}" 2>/dev/null)

# ---------------------------------------------------------------------------
# Report results
# ---------------------------------------------------------------------------
if [[ -n "$VIOLATIONS" ]]; then
    echo "REQ-70.5-8 source-grep gate FAILED — bare dict returns found on dispatch path:"
    echo ""
    echo "$VIOLATIONS"
    echo "To fix: either rename the function to start with '_' (if it is a private helper)"
    echo "or add '# PROVENANCE-EXEMPT' to the return line with a reason."
    echo ""
    echo "See VM107/tools/no-bare-dict-return.sh for exemption rules."
    exit 1
fi

echo "REQ-70.5-8 source-grep gate green. No bare dict dispatch-path returns found."
exit 0
