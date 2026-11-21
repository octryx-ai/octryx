"""The parts of a system prompt: the stable sections, each with its content trust, and the dynamic part.

The stable part is cacheable. Each of its sections has a trust level (``content_security.message_trust``),
derived from the source of its actual text:

- a section rendered from the prompt catalog (the variant template, the fence line, the mode definition, the
  dynamic-context line, the thinking mode, the instruction precedence, the skill discovery lines) is a platform
  instruction only when every catalog body it used is the shipped seed (``prompt_catalog.is_shipped_seed``); a
  published override makes it administrator-authored (:func:`catalog_section`);
- administrator-authored text: the selected agent's blueprint and reply format, the workflow catalog built from
  Workspace workflows;
- untrusted: the person's communication preferences (they carry the person's own text).

The dynamic part (runtime environment, entities, compaction, checkpoint, evidence, repository knowledge, memory)
is untrusted. ``run_context_messages.build_prompt_messages`` sends one system message per run of sections with
the same trust; the content policies check each according to its level.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ....services.content_security.message_trust import TRUST_AUTHORED, TRUST_PLATFORM_INSTRUCTION, TRUST_UNTRUSTED
from ....services.prompt_catalog import ResolvedPrompt, bound_prompt_set, is_shipped_seed, rendered_prompts


@dataclass(frozen=True)
class PromptSection:
    text: str
    trust: str


def platform_section(text: str) -> PromptSection:
    return PromptSection(text, TRUST_PLATFORM_INSTRUCTION)


def authored_section(text: str) -> PromptSection:
    return PromptSection(text, TRUST_AUTHORED)


def untrusted_section(text: str) -> PromptSection:
    return PromptSection(text, TRUST_UNTRUSTED)


@dataclass(frozen=True)
class CatalogText:
    """A text and the catalog bodies it was rendered from (including the ones of texts it carries)."""

    text: str
    sources: tuple[ResolvedPrompt, ...] = ()


def rendered(render: Callable[[], str], *carried: CatalogText) -> CatalogText:
    """``render()`` with the catalog bodies it used, plus those of the ``carried`` texts it interpolates."""
    with rendered_prompts() as used:
        text = render()
    return CatalogText(text, (*used, *(source for item in carried for source in item.sources)))


def keyed(text: str, keys: Iterable[str]) -> CatalogText:
    """A text rendered earlier from ``keys`` of the bound turn set (no bound set: the sources are unknown)."""
    prompt_set = bound_prompt_set()
    if prompt_set is None:
        return CatalogText(text, (ResolvedPrompt(key="", body="", version=0, digest="", source="unknown"),))
    return CatalogText(text, tuple(prompt_set.resolved(key) for key in keys))


def catalog_section(item: CatalogText) -> PromptSection:
    """Platform instruction text only when every source is the shipped seed; an override is authored."""
    shipped = all(is_shipped_seed(source) for source in item.sources)
    return PromptSection(item.text, TRUST_PLATFORM_INSTRUCTION if shipped else TRUST_AUTHORED)


@dataclass(frozen=True)
class SystemPromptParts:
    """Stable and volatile prompt segments used to place provider cache points safely."""

    stable_sections: tuple[PromptSection, ...] = ()
    dynamic: str = ""

    @property
    def stable(self) -> str:
        return "\n".join(section.text for section in self.stable_sections)

    @property
    def combined(self) -> str:
        return "\n".join(part for part in (self.stable, self.dynamic) if part.strip())


__all__ = [
    "CatalogText",
    "PromptSection",
    "SystemPromptParts",
    "authored_section",
    "catalog_section",
    "keyed",
    "platform_section",
    "rendered",
    "untrusted_section",
]
