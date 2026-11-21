"""The code style in a few lines: for the agent of every changing phase (its contract) and as the reviewer's
checklist (the engines get the style as contract, the reviewer as checklist). Short on purpose: the
platform measures the countable rules itself, the text tells the agent what to aim for before it hits them."""

from __future__ import annotations

from typing import Any

from .l10n_check import merge_command

MAX_LAYOUT = 8


def _general(style: dict[str, Any]) -> list[str]:
    general = dict(style.get("general") or {})
    lines = []
    files, tests, functions = (general.get("max_lines_per_file"), general.get("tests_max_lines"),
                               general.get("max_function_lines"))
    if files:
        lines.append(f"Files at most {files} lines" + (f" (tests {tests})" if tests else "")
                     + (f"; functions at most {functions} lines" if functions else "")
                     + ": split by topic before a file reaches the limit.")
    reasons = sorted({str(row.get("reason")) for row in general.get("exclude") or [] if isinstance(row, dict)})
    if reasons:
        lines.append("Not counted: " + ", ".join(reasons) + " files.")
    comments = dict(general.get("comments") or {})
    rules = [text for flag, text in (("public_api_doc", "public APIs have a doc comment"),
                                     ("no_commented_code", "no commented-out code"))
             if comments.get(flag)]
    if comments.get("todo_requires_ticket") and comments.get("todo_pattern"):
        rules.append("a TODO names its ticket, e.g. TODO(ABC-123)")
    if rules:
        lines.append("Comments: " + "; ".join(rules) + ".")
    l10n = dict(general.get("l10n") or {})
    if l10n.get("enabled", True) and l10n:
        lines.append(f"Translations: UI text goes into the catalogs, never into code; source language "
                     f"{l10n.get('source_locale') or 'en'}; every language has the same keys and placeholders; ICU "
                     f"MessageFormat for plurals, gender and variables; at most {l10n.get('max_keys_per_file') or 400} "
                     "keys per file, then split per feature.")
    if (diagrams := diagram_rule(general.get("diagrams"))):
        lines.append(diagrams)
    return lines


DIAGRAM_NAMES = {"architecture": "architecture.drawio (modules and layers, including where data is persisted)",
                 "navigation": "navigation.drawio (the screens and how the user moves between them)",
                 "data_flow": "data-flow.drawio (where data comes from, is transformed and stored)"}


def diagram_rule(diagrams: Any) -> str:
    """The agent's rule for the app's draw.io diagrams; ``""`` when switched off."""
    config = dict(diagrams or {}) if isinstance(diagrams, dict) else {}
    if not config or config.get("enabled") is False:
        return ""
    folder, images = config.get("folder") or "docs/diagrams", config.get("images") or "docs/images"
    kinds = [DIAGRAM_NAMES[kind] for kind in config.get("kinds") or [] if kind in DIAGRAM_NAMES]
    return (f"Diagrams: keep draw.io diagrams of the app in {folder}/ inside the app folder: {'; '.join(kinds)}. "
            "Create them when the app has none; when your change adds, removes or renames a module, a screen, the "
            "persistence or a data flow, update the existing diagram (never a second one of the same kind); "
            "otherwise leave them unchanged. Every box is labelled with the real module, class or screen name from "
            "the code, nothing planned or invented. The platform exports each diagram to "
            f"{images}/<name>.png when the phase ends; reference that PNG in the README (or the docs page) "
            "under a short heading.")


def _languages(style: dict[str, Any]) -> list[str]:
    lines = []
    for name, rules in sorted(dict(style.get("languages") or {}).items()):
        layout = list(dict(rules.get("layout") or {}).get("patterns") or [])
        naming = dict(rules.get("naming") or {})
        parts = []
        if layout:
            parts.append("code under " + ", ".join(layout[:MAX_LAYOUT]))
        if naming.get("file"):
            parts.append(f"file names match {naming['file']}")
        tools = [str(dict(rules.get(kind) or {}).get("command") or "").replace(" {files}", "").replace(
            " --config {platform_config}", "") for kind in ("formatter", "linter")
            if dict(rules.get(kind) or {}).get("enabled", True) and dict(rules.get(kind) or {}).get("command")]
        if tools:
            parts.append("run " + " and ".join(f"`{tool}`" for tool in tools) + " before you finish (the platform "
                         "runs them too; the repository's own configuration wins)")
        l10n = dict(rules.get("l10n") or {})
        if l10n.get("files") and l10n.get("enabled", True):
            parts.append(f"translations per feature in {', '.join(l10n['files'][:2])} ({l10n.get('format')}), keys "
                         "prefixed with their feature" + (f" and matching {l10n['key_pattern']}"
                                                          if l10n.get("key_pattern") else ""))
            target = str(dict(l10n.get("merged") or {}).get("target") or "")
            command = merge_command(l10n)
            if target and command:
                parts.append(f"merge them with `{command}` in the repository's setup before generating; never edit "
                             f"{target} by hand")
        if rules.get("rules") and rules.get("rules") != dict(style.get("general") or {}).get("rules"):
            parts.append(str(rules["rules"]).rstrip("."))
        if parts:
            lines.append(f"{name}: " + "; ".join(parts) + ".")
    return lines


def agent_brief(style: dict[str, Any] | None) -> str:
    """The style for a changing phase's agent; ``""`` without a style."""
    if not style:
        return ""
    rules = str(dict(style.get("general") or {}).get("rules") or "").strip()
    lines = ["Code style of this installation (the platform checks the countable rules and keeps the phase open "
             "until they hold):", *_general(style), *_languages(style), *([f"Team rules: {rules}"] if rules else [])]
    return "\n".join(f"- {line}" if index else line for index, line in enumerate(lines))


REVIEW_INSTRUCTION = (
    "The block \"code style checklist\" is the installation's code style. The platform already measured file and "
    "function lengths, file names, layout, TODOs and commented-out code. Judge what it cannot measure (doc comments of "
    "public APIs, whether the layout and the split into modules make sense, names inside the code) and report each "
    "violation as a finding whose fix starts with \"Style (<rule>):\"; a style finding is low or medium, never high.")


def reviewer_checklist(style: dict[str, Any] | None) -> str:
    """The reviewer's style checklist (data: it goes into a fence, the instruction stays outside); ``""`` without."""
    brief = agent_brief(style)
    return brief.split("\n", 1)[1] if "\n" in brief else ""


__all__ = ["REVIEW_INSTRUCTION", "agent_brief", "reviewer_checklist"]
