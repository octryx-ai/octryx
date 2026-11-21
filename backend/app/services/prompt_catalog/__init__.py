"""Governed prompt catalog: every agent-facing prompt text is data; code holds only the seed.

* ``contract`` - key spec, placeholder validation, rendering, the closed refusal.
* ``seeds`` / ``registry`` - the seed texts and the closed key registry built from them.
* ``resolver`` / ``prompt_set`` - per-turn resolution (agent definition > Workspace >
  global published > seed), the bound turn set and its audit record.
* ``seeding`` - idempotent seed from code.
* ``lifecycle`` / ``governance`` / ``views`` - the admin API's draft, review, publish,
  retire, list, detail and diff.
"""

from __future__ import annotations

from .contract import PROMPT_TEMPLATE_UNAVAILABLE, PromptKeySpec, PromptTemplateUnavailableError
from .prompt_set import (
    PROMPT_TEMPLATES_TRACE_KEY,
    PromptSet,
    ResolvedPrompt,
    bind_prompt_set,
    bound_prompt_set,
    bound_prompt_trace_record,
    prompt_set_scope,
    render_prompt,
    rendered_prompts,
)
from .registry import prompt_key_registry, prompt_key_spec
from .resolver import is_shipped_seed, resolve_prompt_set, seed_prompt_set, shipped_seed_text

__all__ = [
    "PROMPT_TEMPLATES_TRACE_KEY",
    "PROMPT_TEMPLATE_UNAVAILABLE",
    "PromptKeySpec",
    "PromptSet",
    "PromptTemplateUnavailableError",
    "ResolvedPrompt",
    "bind_prompt_set",
    "bound_prompt_set",
    "bound_prompt_trace_record",
    "is_shipped_seed",
    "prompt_key_registry",
    "prompt_key_spec",
    "prompt_set_scope",
    "render_prompt",
    "rendered_prompts",
    "resolve_prompt_set",
    "seed_prompt_set",
    "shipped_seed_text",
]
