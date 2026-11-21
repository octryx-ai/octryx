"""Literal environment values never leave the platform's Kubernetes tools.

A pod template may carry a password written as a plain ``env[].value``. The tools run with the API's credentials and
answer an agent, so every literal ``value`` of an ``env`` entry (containers, init and ephemeral containers, in pods
and in every workload's pod template) is shown as ``<set>``; ``valueFrom`` references stay visible because they only
name a Secret or a field. ``kubectl.kubernetes.io/last-applied-configuration`` repeats the whole spec, so that
annotation is masked the same way.

:func:`mask_kubectl_output` covers ``run_kubectl``'s text: JSON and YAML are parsed, masked and printed again (an
answer that cannot be parsed is withheld, fail-closed); ``describe`` text has its ``Environment:`` blocks masked.
:func:`kubectl_env_template_refusal` refuses the template formats (``jsonpath``, ``go-template``, ``custom-columns``)
on resources with a pod template: they could print a value this module never sees as a structure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import yaml

from .kubernetes_kubectl_flags import parse_kubectl_args

MASK = "<set>"
LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"
WITHHELD = "<output withheld: its environment values could not be masked>"
KUBECTL_ENV_TEMPLATE_REFUSED = "kubectl_env_template_refused"

# Resources whose objects carry containers (a pod or a pod template), with their short names; "all" lists several.
_POD_TEMPLATE_RESOURCES = frozenset({
    "pod", "pods", "po", "deployment", "deployments", "deploy", "statefulset", "statefulsets", "sts", "daemonset",
    "daemonsets", "ds", "replicaset", "replicasets", "rs", "replicationcontroller", "replicationcontrollers", "rc",
    "job", "jobs", "cronjob", "cronjobs", "cj", "podtemplate", "podtemplates", "all",
})
_TEMPLATE_FORMATS = frozenset({"jsonpath", "jsonpath-as-json", "go-template", "template", "custom-columns"})
_KEEP_DESCRIBE_VALUES = ("<set to ", "<none>", "(v1:")


def mask_env(value: Any) -> Any:
    """``value`` (any decoded Kubernetes answer) with every literal env value and the last-applied copy masked."""
    if isinstance(value, list):
        return [mask_env(item) for item in value]
    if not isinstance(value, dict):
        return value
    masked: dict[str, Any] = {}
    for key, item in value.items():
        if key == "env" and isinstance(item, list):
            masked[key] = [{**entry, "value": MASK} if isinstance(entry, dict) and "value" in entry else mask_env(entry)
                           for entry in item]
        elif key == "annotations" and isinstance(item, dict) and LAST_APPLIED in item:
            masked[key] = {**item, LAST_APPLIED: _mask_last_applied(item[LAST_APPLIED])}
        else:
            masked[key] = mask_env(item)
    return masked


def _mask_last_applied(text: Any) -> str:
    try:
        return json.dumps(mask_env(json.loads(str(text))), separators=(",", ":"))
    except ValueError:
        return MASK


def _output_format(args: Sequence[str]) -> str:
    parsed = parse_kubectl_args(args)
    if parsed is None:
        return ""
    formats = [value.split("=", 1)[0] for name, value in parsed.values if name == "output"]
    return formats[-1] if formats else ""


def _leaf(args: Sequence[str]) -> str:
    parsed = parse_kubectl_args(args)
    return str(parsed.leaf or "") if parsed is not None else ""


def mask_kubectl_output(args: Sequence[str], stdout: str) -> str:
    """``stdout`` of ``kubectl <args>`` with literal env values masked; withheld when JSON/YAML cannot be parsed."""
    if not stdout:
        return stdout
    output = _output_format(args)
    if output == "json":
        try:
            return json.dumps(mask_env(json.loads(stdout)), indent=2)
        except ValueError:
            return WITHHELD
    if output == "yaml":
        try:
            documents = [mask_env(doc) for doc in yaml.safe_load_all(stdout)]
        except yaml.YAMLError:
            return WITHHELD
        return yaml.safe_dump_all(documents, sort_keys=False)
    if _leaf(args) == "describe":
        return mask_describe(stdout)
    return stdout


_BLOCK_START = re.compile(r"^(?P<indent>\s*)Environment:\s*(?P<rest>.*)$")
_ENTRY = re.compile(r"^(?P<lead>\s*[A-Za-z_][A-Za-z0-9_.-]*:\s+)(?P<value>.*)$")


def mask_describe(text: str) -> str:
    """``kubectl describe`` text with the values in its ``Environment:`` blocks masked (references kept)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    block_indent: int | None = None
    for line in lines:
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if block_indent is not None:
            indent = len(body) - len(body.lstrip())
            if body.strip() and indent <= block_indent:
                block_indent = None
            elif body.strip():
                entry = _ENTRY.match(body)
                if entry and entry.group("value").strip().startswith(_KEEP_DESCRIBE_VALUES):
                    out.append(line)
                elif entry:
                    out.append(f"{entry.group('lead')}{MASK}{ending}")
                else:
                    out.append(f"{' ' * indent}{MASK}{ending}")  # a continued multi-line value
                continue
        start = _BLOCK_START.match(body)
        if start and not start.group("rest").strip():
            block_indent = len(start.group("indent"))
        out.append(line)
    return "".join(out)


def kubectl_env_template_refusal(args: Sequence[str]) -> str | None:
    """Refuse a template output format on a resource with containers (it could print env values unmasked)."""
    parsed = parse_kubectl_args(args)
    if parsed is None or parsed.leaf != "get" or _output_format(args) not in _TEMPLATE_FORMATS:
        return None
    words = [parsed.positionals[0], *[word for word in parsed.positionals[1:] if "/" in word]] if parsed.positionals \
        else []
    for word in words:
        for part in str(word).split(","):
            if part.split("/", 1)[0].split(".", 1)[0].strip().lower() in _POD_TEMPLATE_RESOURCES:
                return KUBECTL_ENV_TEMPLATE_REFUSED
    return None
