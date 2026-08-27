---
agent: disagree-agent
family: markets
status: built
authority: propose
trigger: [event-driven]
contract_version: 1
---

# Disagree Agent

Complete frontmatter + all 14 sections (so check-(b) stays quiet), but §6 documents a
tool (`tool_x`) the profile does NOT grant (it is in `denied_tools`) — a tools/authority
disagreement that check-(c) must flag.

## 1. Mission
Mission.

## 2. Responsibilities
- Do.

## 3. Non-responsibilities
- Nothing.

## 4. Trigger model
event-driven.

## 5. Inputs
Typed.

## 6. Tools
- `tool_a` — granted.
- `tool_x` — NOT granted (denied in the profile) → disagreement.

## 7. Memory
None.

## 8. Reasoning outputs
Emits contract.

## 9. Confidence & evidence
Decomposed.

## 10. Authority
- May: propose. May NOT: approve.

## 11. Collaboration
- Invoked by: orchestrator.

## 12. Lifecycle
Ephemeral.

## 13. Failure behaviour
| Mode | Response | Outcome |
|---|---|---|

## 14. Evaluation
- metric — target.
