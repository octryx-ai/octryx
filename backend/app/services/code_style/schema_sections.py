"""The validation of a style profile's structured sections (``schema``)."""

from __future__ import annotations

import re
from typing import Any

from .schema_values import (
    COMMENT_FLAGS,
    DIAGRAM_KINDS,
    EXCLUDE_REASONS,
    HARDCODED_LEVELS,
    KEEPABLE_RULES,
    L10N_FORMATS,
    MAX_COMMAND,
    MAX_GLOBS,
    CodeStyleError,
    _globs,
    _regex,
)


def _exclude(rows: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > MAX_GLOBS:
        raise CodeStyleError("invalid_exclude", f"{path}.exclude")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) - {"glob", "reason", "keep"} or row.get("reason", "other") not in \
                EXCLUDE_REASONS or not set(row.get("keep") or []) <= set(KEEPABLE_RULES):
            raise CodeStyleError("invalid_exclude", f"{path}.exclude[{index}]")
        out.append({"glob": _globs([row.get("glob")], f"{path}.exclude[{index}].glob")[0],
                    "reason": row.get("reason", "other"),
                    **({"keep": list(row["keep"])} if row.get("keep") else {})})
    return out


def _comments(comments: Any, path: str) -> dict[str, Any]:
    if not isinstance(comments, dict) or set(comments) - {*COMMENT_FLAGS, "todo_pattern"}:
        raise CodeStyleError("invalid_comments", f"{path}.comments")
    out: dict[str, Any] = {}
    for flag in COMMENT_FLAGS:
        if comments.get(flag) is not None:
            if type(comments[flag]) is not bool:
                raise CodeStyleError("invalid_flag", f"{path}.comments.{flag}")
            out[flag] = comments[flag]
    if comments.get("todo_pattern") is not None:
        out["todo_pattern"] = _regex(comments["todo_pattern"], f"{path}.comments.todo_pattern")
    return out


def _layout(layout: Any, path: str) -> dict[str, Any]:
    if not isinstance(layout, dict) or set(layout) - {"roots", "patterns"}:
        raise CodeStyleError("invalid_layout", f"{path}.layout")
    return {key: _globs(layout[key], f"{path}.layout.{key}") for key in ("roots", "patterns")
            if layout.get(key) is not None}


def _naming(naming: Any, path: str) -> dict[str, Any]:
    if not isinstance(naming, dict) or set(naming) - {"file", "test_suffix"}:
        raise CodeStyleError("invalid_naming", f"{path}.naming")
    out: dict[str, Any] = {}
    if naming.get("file") is not None:
        out["file"] = _regex(naming["file"], f"{path}.naming.file")
    if naming.get("test_suffix") is not None:
        if not isinstance(naming["test_suffix"], str) or len(naming["test_suffix"]) > 40:
            raise CodeStyleError("invalid_naming", f"{path}.naming.test_suffix")
        out["test_suffix"] = naming["test_suffix"]
    return out


def _tool_variants(variants: Any, path: str) -> list[dict[str, Any]]:
    # The build's own setup first (Spotless, Checkstyle in Gradle / Maven): [{when: [config], command}].
    if not isinstance(variants, list) or len(variants) > 10 or any(
            not isinstance(item, dict) or set(item) != {"when", "command"}
            or not isinstance(item["command"], str) or len(item["command"]) > MAX_COMMAND
            for item in variants):
        raise CodeStyleError("invalid_tool", f"{path}.variants")
    return [{"when": _globs(item["when"], f"{path}.variants.when"),
             "command": item["command"].strip()} for item in variants]


def _tool_levels(levels: Any, path: str) -> dict[str, str]:
    # {level: a regex over one output line}; ``blocking``: the levels that make a failed run red.
    if not isinstance(levels, dict) or len(levels) > 10 or any(
            not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,20}", key) for key in levels):
        raise CodeStyleError("invalid_tool", f"{path}.levels")
    return {key: _regex(pattern, f"{path}.levels.{key}") for key, pattern in levels.items()}


def _tool(tool: Any, path: str) -> dict[str, Any]:
    """One formatter or linter section; ``path`` already names the kind."""
    if not isinstance(tool, dict) or set(tool) - {"command", "repo_config_command", "config_files", "enabled",
                                                   "variants", "levels", "blocking", "outside_sandbox"}:
        raise CodeStyleError("invalid_tool", path)
    out: dict[str, Any] = {}
    for key in ("command", "repo_config_command"):
        if tool.get(key) is not None:
            if not isinstance(tool[key], str) or not tool[key].strip() or len(tool[key]) > MAX_COMMAND:
                raise CodeStyleError("invalid_tool", f"{path}.{key}")
            out[key] = tool[key].strip()
    if tool.get("config_files") is not None:
        out["config_files"] = _globs(tool["config_files"], f"{path}.config_files")
    if tool.get("variants") is not None:
        out["variants"] = _tool_variants(tool["variants"], path)
    if tool.get("levels") is not None:
        out["levels"] = _tool_levels(tool["levels"], path)
    if tool.get("blocking") is not None:
        blocking = tool["blocking"]
        if not isinstance(blocking, list) or any(not isinstance(item, str) or len(item) > 20
                                                 for item in blocking):
            raise CodeStyleError("invalid_tool", f"{path}.blocking")
        out["blocking"] = list(blocking)
    if tool.get("enabled") is not None:
        if type(tool["enabled"]) is not bool:
            raise CodeStyleError("invalid_flag", f"{path}.enabled")
        out["enabled"] = tool["enabled"]
    if tool.get("outside_sandbox") is not None:
        # The tool cannot run inside the agent's sandbox (Dart / Flutter write their SDK cache): the
        # launcher runs it only as its own call, outside (``local_tests``).
        if type(tool["outside_sandbox"]) is not bool:
            raise CodeStyleError("invalid_flag", f"{path}.outside_sandbox")
        out["outside_sandbox"] = tool["outside_sandbox"]
    return out


def _diagrams(value: Any, path: str) -> dict[str, Any]:
    """The app's draw.io diagrams: ``{enabled, folder, images, kinds}``."""
    if not isinstance(value, dict) or set(value) - {"enabled", "folder", "images", "kinds"}:
        raise CodeStyleError("invalid_diagrams", path)
    out: dict[str, Any] = {}
    if value.get("enabled") is not None:
        if type(value["enabled"]) is not bool:
            raise CodeStyleError("invalid_flag", f"{path}.enabled")
        out["enabled"] = value["enabled"]
    for key in ("folder", "images"):
        if value.get(key) is not None:
            folder = value[key]
            if not isinstance(folder, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*", folder) or \
                    ".." in folder.split("/"):
                raise CodeStyleError("invalid_diagrams", f"{path}.{key}")
            out[key] = folder
    if value.get("kinds") is not None:
        kinds = value["kinds"]
        if not isinstance(kinds, list) or set(kinds) - set(DIAGRAM_KINDS):
            raise CodeStyleError("invalid_diagrams", f"{path}.kinds")
        out["kinds"] = list(dict.fromkeys(kinds))
    return out


def _l10n(value: Any, path: str) -> dict[str, Any]:
    keys = {"format", "files", "source_locale", "key_pattern", "max_keys_per_file", "hardcoded_text", "enabled",
            "merged"}
    if not isinstance(value, dict) or set(value) - keys:
        raise CodeStyleError("invalid_l10n", path)
    out: dict[str, Any] = {}
    if value.get("format") is not None:
        if value["format"] not in L10N_FORMATS:
            raise CodeStyleError("invalid_l10n", f"{path}.format")
        out["format"] = value["format"]
    if value.get("files") is not None:
        out["files"] = _globs(value["files"], f"{path}.files")
    if value.get("source_locale") is not None:
        if not isinstance(value["source_locale"], str) or not re.fullmatch(r"[a-z]{2,3}([_-][A-Za-z]{2,4})?",
                                                                           value["source_locale"]):
            raise CodeStyleError("invalid_l10n", f"{path}.source_locale")
        out["source_locale"] = value["source_locale"]
    if value.get("key_pattern") is not None:
        out["key_pattern"] = _regex(value["key_pattern"], f"{path}.key_pattern")
    if value.get("max_keys_per_file") is not None:
        if type(value["max_keys_per_file"]) is not int or not 0 <= value["max_keys_per_file"] <= 100000:
            raise CodeStyleError("invalid_number", f"{path}.max_keys_per_file")
        out["max_keys_per_file"] = value["max_keys_per_file"]
    if value.get("hardcoded_text") is not None:
        if value["hardcoded_text"] not in HARDCODED_LEVELS:
            raise CodeStyleError("invalid_l10n", f"{path}.hardcoded_text")
        out["hardcoded_text"] = value["hardcoded_text"]
    if value.get("enabled") is not None:
        if type(value["enabled"]) is not bool:
            raise CodeStyleError("invalid_flag", f"{path}.enabled")
        out["enabled"] = value["enabled"]
    if value.get("merged") is not None:
        # Where the tool knows one file per language (gen-l10n, gettext): the features' files merged into ``target``
        # (``<lang>``) by ``command`` (a template: {format}, {features}, {target}), never edited by hand.
        # ``generated``: what the toolchain writes from the merged files; ``hand_edit``: how a change to either
        # without a feature file counts (findings 39/55: agents hand-edited the merged ARB and the generated Dart).
        merged = value["merged"]
        keys = {"target", "generated", "hand_edit", "command"}
        if not isinstance(merged, dict) or "target" not in merged or set(merged) - keys \
                or not isinstance(merged["target"], str) or "<lang>" not in merged["target"] \
                or len(merged["target"]) > 200 or merged.get("hand_edit", "warning") not in ("warning", "error"):
            raise CodeStyleError("invalid_l10n", f"{path}.merged")
        out["merged"] = {"target": merged["target"].strip()}
        if merged.get("generated") is not None:
            generated = merged["generated"]
            if not isinstance(generated, list) or len(generated) > 10 or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 200 for item in generated):
                raise CodeStyleError("invalid_l10n", f"{path}.merged.generated")
            out["merged"]["generated"] = [item.strip() for item in generated]
        if merged.get("hand_edit") is not None:
            out["merged"]["hand_edit"] = merged["hand_edit"]
        if merged.get("command") is not None:
            if not isinstance(merged["command"], str) or not merged["command"].strip() \
                    or len(merged["command"]) > MAX_COMMAND:
                raise CodeStyleError("invalid_l10n", f"{path}.merged.command")
            out["merged"]["command"] = merged["command"].strip()
    return out
