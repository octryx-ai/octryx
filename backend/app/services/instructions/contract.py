"""The closed contract of Instructions: layers, their order and budgets, digests, token estimates.

Order the agent reads (fixed and visible): System prompt texts → agent instructions → Workspace
instructions (global and Workspace scope) → workflow instructions (bound to the selected workflow) →
skills on demand. Each layer has a token budget; going over it is a conflict finding at publish time,
never a silent truncation at run time.
"""

from __future__ import annotations

from hashlib import sha256

from ...models.runtime.instruction import INSTRUCTION_BINDING_ON_REQUEST, INSTRUCTION_SCOPE_AGENT, Instruction

LAYER_AGENT = "agent"
LAYER_WORKSPACE = "workspace"
LAYER_WORKFLOW = "workflow"
# Never in the prompt; read by exact key only.
LAYER_ON_REQUEST = "on_request"
LAYER_ORDER: tuple[str, ...] = (LAYER_AGENT, LAYER_WORKSPACE, LAYER_WORKFLOW)
LAYER_BUDGETS: dict[str, int] = {LAYER_AGENT: 800, LAYER_WORKSPACE: 1500, LAYER_WORKFLOW: 1500, LAYER_ON_REQUEST: 3000}
MAX_BODY_CHARS = 12_000
KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,119}$"


def layer_of(instruction: Instruction) -> str:
    if instruction.binding == INSTRUCTION_BINDING_ON_REQUEST:
        return LAYER_ON_REQUEST
    if instruction.workflow_key:
        return LAYER_WORKFLOW
    return LAYER_AGENT if instruction.scope_type == INSTRUCTION_SCOPE_AGENT else LAYER_WORKSPACE


def token_estimate(body: str) -> int:
    return (len(str(body or "")) + 3) // 4


def body_digest(body: str) -> str:
    return "sha256:" + sha256(str(body or "").encode("utf-8")).hexdigest()


__all__ = [
    "KEY_PATTERN",
    "LAYER_AGENT",
    "LAYER_BUDGETS",
    "LAYER_ON_REQUEST",
    "LAYER_ORDER",
    "LAYER_WORKFLOW",
    "LAYER_WORKSPACE",
    "MAX_BODY_CHARS",
    "body_digest",
    "layer_of",
    "token_estimate",
]
