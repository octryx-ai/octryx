"""Security review of a skill version: a deterministic scanner plus a human reviewer."""

from __future__ import annotations

import re
from typing import Any

from ..model_gateway.inbound.secret_scan import secret_kinds
from .bundle import KIND_SCRIPT, classify
from .spec import EXECUTION_FRONTMATTER_KEYS, SKILL_FILE, SkillSpecError, parse_skill_md, stripped_keys

HIGH, MEDIUM, INFO = "high", "medium", "info"
_SHELL_INLINE = re.compile(r"!`[^`\n]+`")
_SHELL_FENCE = re.compile(r"^\s*(```|~~~)!")
_NETWORK = re.compile(r"\b(?:curl|wget|Invoke-WebRequest)\b|https?://|\brequests\.|\bfetch\(")
_CHANGING = (
    ("kubectl", re.compile(r"\bkubectl\s+(?:[^\n|;&]*\s)?(?:apply|delete|replace|patch|scale|drain)\b")),
    ("helm", re.compile(r"\bhelm\s+(?:install|upgrade|uninstall|rollback)\b")),
    ("terraform", re.compile(r"\bterraform\s+(?:apply|destroy|import|state\s+(?:rm|mv|push))\b")),
)
_DRY_RUN_CLIENT = re.compile(r"--dry-run=client\b")


def _finding(rule: str, severity: str, message: str, *, file: str | None = None, line: int | None = None,
             effect: str = "shown", acknowledge: bool = False, blocks: bool = False) -> dict[str, Any]:
    location = f":{file}" if file else ""
    location += f":{line}" if line else ""
    return {"id": f"{rule}{location}", "rule": rule, "severity": severity, "message": message, "file": file,
            "line": line, "effect": effect, "acknowledge": acknowledge, "blocks": blocks}


def _markdown(path: str) -> bool:
    return path.lower().endswith((".md", ".markdown"))


def _line_findings(path: str, text: str, *, script: bool) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _markdown(path) and (_SHELL_INLINE.search(line) or _SHELL_FENCE.match(line)):
            found.append(_finding("shell_injection", HIGH, "Shell injection block: Claude Code would run it before "
                                  "the model sees the skill; delivery turns skill shell execution off.",
                                  file=path, line=number, effect="not executed", acknowledge=True))
        for kind in secret_kinds(line):
            found.append(_finding("secret", HIGH, f"Credential material ({kind}); remove it before publishing.",
                                  file=path, line=number, effect="publish refused", blocks=True))
        if script and _NETWORK.search(line):
            found.append(_finding("network", MEDIUM, "Network access in a script.", file=path, line=number))
        for program, pattern in _CHANGING:
            if pattern.search(line) and not (program == "helm" and _DRY_RUN_CLIENT.search(line)):
                found.append(_finding(
                    "changing_command", MEDIUM if script else INFO,
                    f"Changing {program} command; it runs only as a governed tool call.", file=path, line=number,
                    effect="governed tool call"))
    return found


def _frontmatter_findings(texts: dict[str, str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    try:
        frontmatter = parse_skill_md(texts[SKILL_FILE]).frontmatter if SKILL_FILE in texts else {}
    except SkillSpecError:
        frontmatter = {}
    for key in stripped_keys(frontmatter):
        execution = key in EXECUTION_FRONTMATTER_KEYS
        found.append(_finding(
            "execution_frontmatter" if execution else "other_frontmatter", MEDIUM if execution else INFO,
            f"Frontmatter `{key}` is stripped on delivery" + (" (it would grant tools or change execution)."
                                                             if execution else "."),
            file=SKILL_FILE, effect="stripped"))
    for path, text in texts.items():
        if path != SKILL_FILE and _markdown(path) and text.startswith("---"):
            try:
                parse_skill_md(text)
            except SkillSpecError:
                continue
            found.append(_finding("extra_frontmatter", INFO, "A reference file with its own frontmatter; it is "
                                  "delivered as a reference, never as a second skill.", file=path))
    return found


def _mcp_findings(launch: dict[str, Any] | None) -> list[dict[str, Any]]:
    spec = launch or {}
    found = [_finding("mcp_local_process", MEDIUM, f"Starts a local process: {spec.get('command')} "
                      f"{' '.join(spec.get('args') or [])}".strip(), effect="started only when mcp_policy allows it")]
    if spec.get("image") and not spec.get("image_digest"):
        found.append(_finding("mcp_image_tag", MEDIUM, f"Image by tag ({spec['image']}); record its digest at "
                              "review — sessions start the digest.", effect="publish refused until recorded"))
    for name in spec.get("passthrough") or []:
        mapped = name in (spec.get("env_connections") or {})
        found.append(_finding(
            "mcp_credential_passthrough", HIGH if not mapped else INFO,
            f"`{name}` would be taken from the user's shell; it is never passed through"
            + ("; it comes from the mapped named connection." if mapped else "; map a named connection or leave it "
               "unset."), file=name, effect="blocked", acknowledge=not mapped))
    if spec.get("command") == "docker":
        found.append(_finding("mcp_outbound", INFO, "Pulls the image from its registry and may call the network.",
                              effect="client network policy"))
    return found


def scan(kind: str, texts: dict[str, str], *, executable: set[str], scripts_allowed: bool, licence: str | None,
         launch_spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if kind == "mcp_server":
        findings += _mcp_findings(launch_spec)
    for path, text in sorted(texts.items()):
        script = classify(path, text, path in executable) == KIND_SCRIPT
        if script:
            findings.append(_finding(
                "script", HIGH, "Executable file." + (" Delivered: this version allows scripts (running one is still "
                                                      "a governed Bash call)." if scripts_allowed else
                                                      " Withheld on every surface."),
                file=path, effect="delivered (allowed)" if scripts_allowed else "withheld", acknowledge=True))
        findings += _line_findings(path, text, script=script)
    findings += _frontmatter_findings(texts) if kind != "mcp_server" else []
    if not licence:
        findings.append(_finding("licence_missing", HIGH, "No licence: set the SPDX id before publishing.",
                                 effect="publish refused", blocks=True))
    unique: dict[str, dict[str, Any]] = {}
    for item in findings:
        unique.setdefault(item["id"], item)
    order = {HIGH: 0, MEDIUM: 1, INFO: 2}
    return sorted(unique.values(), key=lambda item: (order[item["severity"]], item["id"]))


def summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {HIGH: 0, MEDIUM: 0, INFO: 0}
    for item in findings:
        counts[item["severity"]] += 1
    return counts


def new_findings(draft: list[dict[str, Any]], published: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {item["id"] for item in published}
    return [item for item in draft if item["id"] not in known]


__all__ = ["new_findings", "scan", "summary"]
