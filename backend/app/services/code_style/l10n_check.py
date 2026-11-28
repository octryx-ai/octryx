"""The translations against the style's ``l10n`` rules (``check``)."""

from __future__ import annotations

import re
from typing import Any

from .finding import Finding

MAX_L10N_LISTED = 20


def _l10n_rules(style: dict[str, Any], language: str) -> dict[str, Any]:
    rules = dict(dict(style.get("languages") or {}).get(language) or style.get("general") or {})
    return dict(rules.get("l10n") or {})


def _catalog_findings(catalog: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    files = {str(locale): dict(entry) for locale, entry in dict(catalog.get("files") or {}).items()
             if isinstance(entry, dict)}
    source = str(rules.get("source_locale") or "en")
    namespace = str(catalog.get("namespace") or "")
    if source not in files:
        if not files:
            return []
        first = str(next(iter(files.values())).get("path") or namespace)
        return [Finding("l10n_source", first,
                        f"no {source} file for {namespace or 'the translations'} (the source language)")]
    found: list[Finding] = []
    base = files[source]
    keys = set(base.get("keys") or [])
    limit = int(rules.get("max_keys_per_file") or 0)
    pattern = str(rules.get("key_pattern") or "")
    for locale, entry in sorted(files.items()):
        path = str(entry.get("path") or namespace)
        own = set(entry.get("keys") or [])
        count = int(entry.get("count") or len(own))
        if limit and count > limit:
            found.append(Finding("l10n_max_keys", path, f"{count} keys (max {limit}): split it per feature or "
                                                        "namespace"))
        if locale == source:
            bad = sorted(key for key in own if pattern and not re.search(pattern, key))
            if bad:
                found.append(Finding("l10n_key_pattern", path, f"keys not like {pattern}: "
                                     + ", ".join(bad[:MAX_L10N_LISTED]), severity="warning"))
            continue
        missing, extra = sorted(keys - own), sorted(own - keys)
        if missing:
            found.append(Finding("l10n_missing_keys", path, f"{len(missing)} keys of {source} missing: "
                                 + ", ".join(missing[:MAX_L10N_LISTED])))
        if extra:
            found.append(Finding("l10n_extra_keys", path, f"{len(extra)} keys not in {source}: "
                                 + ", ".join(extra[:MAX_L10N_LISTED]), severity="warning"))
        source_places = dict(base.get("placeholders") or {})
        own_places = dict(entry.get("placeholders") or {})
        differing = sorted(key for key in keys & own if sorted(source_places.get(key) or [])
                           != sorted(own_places.get(key) or []))
        if differing:
            found.append(Finding("l10n_placeholders", path, "placeholders differ from " + source + ": "
                                 + ", ".join(differing[:MAX_L10N_LISTED])))
    return found


def _source_entry(catalog: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(catalog.get("files") or {}).get(str(rules.get("source_locale") or "en")) or {})


def _prefixed(key: str, feature: str, fmt: str) -> bool:
    plain = feature.replace("-", "").replace("_", "").lower()
    if fmt == "arb":
        return key.lower().startswith(plain) and (len(key) == len(plain) or key[len(plain)].isupper())
    return key.startswith(feature + ("-" if fmt == "fluent" else "."))


def _prefix_findings(catalog: dict[str, Any], rules: dict[str, Any]) -> list[Finding]:
    fmt, feature = str(rules.get("format") or ""), str(catalog.get("namespace") or "")
    entry = _source_entry(catalog, rules)
    if fmt == "gettext" or not feature or feature == "app" or not entry:
        return []
    bad = sorted(key for key in entry.get("keys") or [] if not _prefixed(str(key), feature, fmt))
    return [Finding("l10n_key_prefix", str(entry.get("path") or feature), f"keys without the feature prefix "
                    f"{feature}: " + ", ".join(bad[:MAX_L10N_LISTED]), severity="warning")] if bad else []


def _duplicate_findings(style: dict[str, Any], catalogs: list[dict[str, Any]]) -> list[Finding]:
    owners: dict[tuple[str, str], list[str]] = {}
    for catalog in catalogs:
        rules = _l10n_rules(style, str(catalog.get("language") or ""))
        entry = _source_entry(catalog, rules)
        for key in entry.get("keys") or []:
            owners.setdefault((str(catalog.get("language")), str(key)), []).append(str(entry.get("path") or ""))
    return [Finding("l10n_duplicate_key", paths[0], f"key {key} is defined by several features: " + ", ".join(paths))
            for (_language, key), paths in sorted(owners.items()) if len(paths) > 1]


def _target_regex(pattern: str) -> re.Pattern[str]:
    regex = re.escape(pattern).replace(re.escape("**/"), "(?:.*/)?")
    for placeholder in ("<lang>", "<namespace>"):
        regex = regex.replace(re.escape(placeholder), "[^/]+")
    return re.compile("(^|.*/)" + regex.replace(r"\*", "[^/]*") + "$")


def merge_command(l10n: dict[str, Any]) -> str:
    merged = dict(l10n.get("merged") or {})
    template, files = str(merged.get("command") or ""), list(l10n.get("files") or [])
    if not template or not files:
        return ""
    features = str(files[0]).replace("<namespace>", "*")
    return template.format(format=l10n.get("format") or "", features=features, target=merged.get("target") or "")


def _generated_findings(style: dict[str, Any], changed: list[str]) -> list[Finding]:
    found: list[Finding] = []
    for language, rules in sorted(dict(style.get("languages") or {}).items()):
        l10n = dict(dict(rules or {}).get("l10n") or {})
        merged = dict(l10n.get("merged") or {})
        target = str(merged.get("target") or "")
        if not target or not changed:
            continue
        sources = [_target_regex(str(pattern)) for pattern in l10n.get("files") or []]
        outputs = [_target_regex(str(pattern)) for pattern in [target, *(merged.get("generated") or [])]]
        edited = [path for path in changed if any(regex.match(path) for regex in outputs)]
        if edited and not any(regex.match(path) for regex in sources for path in changed):
            command = merge_command(l10n)
            how = f"run `{command}`, then the toolchain's generation" if command else "merge them"
            severity = "error" if merged.get("hand_edit") == "error" else "warning"
            found += [Finding("l10n_generated_edited", path, f"generated ({language}): edit the feature files "
                              f"({', '.join(l10n.get('files') or [])}) and {how}", severity=severity)
                      for path in edited]
    return found


def l10n_findings(style: dict[str, Any], facts: Any) -> list[Finding]:
    if not isinstance(facts, dict) or not style:
        return []
    found: list[Finding] = []
    catalogs = [item for item in facts.get("catalogs") or [] if isinstance(item, dict)]
    for catalog in catalogs:
        rules = _l10n_rules(style, str(catalog.get("language") or ""))
        if rules.get("enabled", True):
            found += _catalog_findings(catalog, rules)
            found += _prefix_findings(catalog, rules)
    found += _duplicate_findings(style, catalogs)
    found += _generated_findings(style, [str(item) for item in facts.get("changed") or []])
    for entry in facts.get("hardcoded") or []:
        if isinstance(entry, list) and len(entry) == 4:
            level = str(_l10n_rules(style, str(entry[3])).get("hardcoded_text") or "warning")
            if level != "off":
                found.append(Finding("l10n_hardcoded_text", str(entry[0]), f"UI text in code: {str(entry[2])[:80]} "
                                     "(put it in the translations)", line=int(entry[1]),
                                     severity="error" if level == "error" else "warning"))
    return found
