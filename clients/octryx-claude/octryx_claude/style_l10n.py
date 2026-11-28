"""The translation catalogs and new hard-coded UI text the platform's code style check needs; the server judges."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

MAX_KEYS = 5000
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_HARDCODED = 100
SKIP_DIRS = {"node_modules", ".dart_tool", "build", ".git", "target", ".venv", "dist", ".gradle"}
_ICU = re.compile(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,}]")
_I18NEXT = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)")
_GETTEXT = re.compile(r"%\(([A-Za-z_]\w*)\)[sdif]|\{([A-Za-z_]\w*)\}")
_PROPERTIES = re.compile(r"\{(\w+)[,}]")
_FLUENT = re.compile(r"\{\s*\$([A-Za-z_][\w-]*)")
HARDCODED = {
    "dart": [re.compile(r"""\bText\(\s*['"]([^'"$]*[A-Za-z]{2,}[^'"]*)['"]"""),
             re.compile(r"""\b(?:title|label|labelText|hintText|tooltip|semanticLabel|helperText)\s*:\s*"""
                        r"""(?:const\s+)?(?:Text\(\s*)?['"]([^'"$]*[A-Za-z]{2,}[^'"]*)['"]""")],
    "typescript": [re.compile(r">\s*([A-Z][A-Za-z ,.!?']{2,}?)\s*<"),
                   re.compile(r"""\b(?:label|placeholder|title|aria-label|alt)=["']([^"'{}]*[A-Za-z]{2,}[^"']*)["']""")],
    "java": [re.compile(r"""\.setText\(\s*"([^"]*[A-Za-z]{2,}[^"]*)\"""")],
    "kotlin": [re.compile(r"""\bText\(\s*(?:text\s*=\s*)?"([^"$]*[A-Za-z]{2,}[^"]*)\"""")],
}
HARDCODED["javascript"] = HARDCODED["typescript"]
_UI_SUFFIX = {"dart": (".dart",), "typescript": (".tsx", ".jsx"), "javascript": (".jsx",), "java": (".java",),
              "kotlin": (".kt",)}


def _pattern(pattern: str) -> tuple[str, re.Pattern[str]]:
    glob = pattern.replace("<lang>", "*").replace("<namespace>", "*")
    regex = re.escape(pattern).replace(re.escape("**/"), "(?:.*/)?")
    regex = regex.replace(re.escape("<lang>"), r"(?P<lang>[A-Za-z_-]+)")
    regex = regex.replace(re.escape("<namespace>"), r"(?P<namespace>[\w.-]+)").replace(r"\*", "[^/]*")
    return glob, re.compile(r"(?:^|.*/)" + regex + "$")


def _walk(root: Path, glob: str) -> list[Path]:
    found = []
    for path in [*root.glob(glob), *root.glob("**/" + glob.removeprefix("**/"))]:
        if path.is_file() and not SKIP_DIRS & set(path.relative_to(root).parts) and path not in found:
            found.append(path)
    return found[:500]


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, item in (value.items() if isinstance(value, dict) else []):
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            out.update(_flatten(item, name))
        else:
            out[name] = str(item)
    return out


def _gettext(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    current: dict[str, str] = {}
    field = ""
    for line in [*text.splitlines(), ""]:
        stripped = line.strip()
        match = re.match(r'(msgid|msgstr)\s+"(.*)"$', stripped)
        if match:
            field = match.group(1)
            current[field] = match.group(2)
        elif stripped.startswith('"') and field:
            current[field] = current.get(field, "") + stripped.strip('"')
        elif not stripped:
            if current.get("msgid"):
                entries[current["msgid"]] = current.get("msgstr", "") or current["msgid"]
            current, field = {}, ""
    return entries


def parse(path: Path, fmt: str) -> dict[str, str]:
    if path.stat().st_size > MAX_CATALOG_BYTES:
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    if fmt in ("arb", "i18next"):
        try:
            data = json.loads(text)
        except ValueError:
            return {}
        flat = _flatten(data)
        return {key: value for key, value in flat.items() if not key.startswith("@")}
    if fmt == "gettext":
        return _gettext(text)
    if fmt == "properties":
        return {match.group(1).strip(): match.group(2) for match in
                re.finditer(r"^\s*([^#!\s][^=:]*?)\s*[=:]\s*(.*)$", text, re.MULTILINE)}
    if fmt == "fluent":
        return {match.group(1): match.group(2) for match in
                re.finditer(r"^([A-Za-z][\w-]*)\s*=\s*(.*)$", text, re.MULTILINE)}
    return {}


def placeholders(message: str, fmt: str) -> list[str]:
    if fmt == "fluent":
        return sorted(set(_FLUENT.findall(message)))
    if fmt == "gettext":
        return sorted({name for pair in _GETTEXT.findall(message) for name in pair if name})
    if fmt == "properties":
        return sorted(set(_PROPERTIES.findall(message)))
    found = set(_ICU.findall(message))
    if fmt == "i18next":
        found |= set(_I18NEXT.findall(message))
    return sorted(found)


def catalogs(root: Path, style: dict[str, Any]) -> list[dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for language, rules in sorted(dict(style.get("languages") or {}).items()):
        l10n = dict(dict(rules or {}).get("l10n") or {})
        fmt = str(l10n.get("format") or "")
        if not fmt or l10n.get("enabled") is False:
            continue
        for pattern in l10n.get("files") or []:
            glob, regex = _pattern(str(pattern))
            for path in _walk(root, glob):
                relative = path.relative_to(root).as_posix()
                match = regex.match(relative)
                if not match:
                    continue
                locale = match.group("lang")
                namespace = match.groupdict().get("namespace") or "app"
                folder = relative[:match.start("lang")]
                try:
                    messages = parse(path, fmt)
                except OSError:
                    continue
                entry = out.setdefault((language, folder, namespace), {"language": language, "namespace": namespace,
                                                                      "folder": folder, "files": {}})
                keys = sorted(messages)[:MAX_KEYS]
                entry["files"][locale] = {"path": relative, "count": len(messages), "keys": keys,
                                          "placeholders": {key: places for key in keys
                                                           if (places := placeholders(messages[key], fmt))}}
    return list(out.values())


def _base_text(root: Path, base: str, name: str) -> str:
    try:
        shown = subprocess.run(["git", "-C", str(root), "cat-file", "-p", f"{base}:{name}"], capture_output=True,
                               timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return shown.stdout.decode("utf-8", "replace") if shown.returncode == 0 else ""


def hardcoded(root: Path, base: str, files: list[str]) -> list[list[Any]]:
    found: list[list[Any]] = []
    for name in files:
        language = next((lang for lang, suffixes in _UI_SUFFIX.items() if name.lower().endswith(suffixes)), None)
        if language is None or re.search(r"(^|/)(test|tests|__tests__)/|_test\.|\.test\.|\.spec\.", name):
            continue
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        before = set(_base_text(root, base, name).splitlines()) if base else set()
        for number, line in enumerate(text.splitlines(), 1):
            if line in before or line.lstrip().startswith(("//", "#", "*", "import ")):
                continue
            for pattern in HARDCODED[language]:
                match = pattern.search(line)
                if match:
                    found.append([name, number, match.group(match.lastindex or 0).strip(), language])
                    break
            if len(found) >= MAX_HARDCODED:
                return found
    return found


def l10n_facts(root: Path, style: dict[str, Any], base: str, files: list[str]) -> dict[str, Any]:
    return {"catalogs": catalogs(root, style), "hardcoded": hardcoded(root, base, files), "changed": files[:500]}


__all__ = ["catalogs", "hardcoded", "l10n_facts", "parse", "placeholders"]
