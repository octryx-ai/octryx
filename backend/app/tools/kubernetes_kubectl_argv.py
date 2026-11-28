"""kubectl argv for the Kubernetes tools, and the one decision on read-only kubectl commands."""

from __future__ import annotations

from collections.abc import Sequence

from .kubernetes_kubectl_flags import CONNECTION_OVERRIDE_FLAGS, parse_kubectl_args

KUBECTL_SUBCOMMAND_MISSING = "kubectl_subcommand_missing"
KUBECTL_SUBCOMMAND_FORBIDDEN = "kubectl_subcommand_forbidden"
# Under an alert scope: the target's namespace only, and no Secret read (a global refusal is separate).
KUBECTL_ARGS_AMBIGUOUS = "kubectl_args_ambiguous"
KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE = "kubectl_all_namespaces_out_of_scope"
NAMESPACE_OUT_OF_SCOPE = "namespace_out_of_scope"
SECRET_READ_OUT_OF_SCOPE = "secret_read_out_of_scope"
# The platform's own Kubernetes tools never read Secret contents, with or without an alert scope:
# they run with the API's credentials. A ConfigMap can hold secrets too, so its data is refused as well;
# listing ConfigMaps by name stays.
KUBECTL_SECRET_READ_REFUSED = "kubectl_secret_read_refused"
_SECRET_READ_LEAVES = frozenset({"get", "describe"})
_SECRET_RESOURCES = frozenset({"secret", "secrets"})
_CONFIGMAP_RESOURCES = frozenset({"configmap", "configmaps", "cm"})
# Output formats that print a resource's data (a plain table or ``name`` does not).
_DATA_OUTPUT_FORMATS = frozenset({"json", "yaml", "jsonpath", "jsonpath-as-json", "go-template", "template",
                                  "custom-columns"})
# Output formats that print the API answer or apply an INLINE template. The ``*-file`` formats
# (``go-template-file``, ``jsonpath-file``, ``custom-columns-file``, ``templatefile``) read a local file
# named by the agent, and so does ``--template`` with them: refused. Anything else fails closed.
INLINE_OUTPUT_FORMATS: frozenset[str] = frozenset({
    "json", "yaml", "wide", "name", "jsonpath", "jsonpath-as-json", "go-template", "template", "custom-columns",
    "plaintext", "plaintext-openapiv2",
})
# Read leaves where a positional word would be a further subcommand (``cluster-info dump`` writes files).
_BARE_LEAVES = frozenset({"cluster-info"})


def kubectl_is_read_only(args: Sequence[str], *, context_selectable: bool = False) -> bool:
    if not args:
        return False
    parsed = parse_kubectl_args(args)
    if parsed is None or parsed.leaf is None:
        return False
    overrides = set(parsed.flags) & CONNECTION_OVERRIDE_FLAGS
    if context_selectable:
        overrides.discard("context")
    if overrides:
        return False
    if any(name == "output" and not _inline_output(value) for name, value in parsed.values):
        return False
    return not (parsed.leaf in _BARE_LEAVES and parsed.positionals)


def _inline_output(value: str) -> bool:
    return value.split("=", 1)[0] in INLINE_OUTPUT_FORMATS


def kubectl_subcommand(args: Sequence[str]) -> str:
    parsed = parse_kubectl_args(args)
    return parsed.path[0] if parsed is not None and parsed.path else ""


def kubectl_subcommand_refusal(args: Sequence[str]) -> str | None:
    if not args:
        return KUBECTL_SUBCOMMAND_MISSING
    if str(args[0]).startswith("-") or not kubectl_is_read_only(args):
        return KUBECTL_SUBCOMMAND_FORBIDDEN
    from .kubernetes_env_mask import kubectl_env_template_refusal  # noqa: PLC0415 - the mask builds on the flags

    return kubectl_secret_read_refusal(args) or kubectl_env_template_refusal(args)


def _typed_words(positionals: Sequence[str]) -> list[str]:
    return [positionals[0], *[word for word in positionals[1:] if "/" in word]] if positionals else []


def _names_kind(word: str, kinds: frozenset[str]) -> bool:
    for part in str(word).split(","):
        if part.split("/", 1)[0].split(".", 1)[0].strip().lower() in kinds:
            return True
    return False


def kubectl_secret_read_refusal(args: Sequence[str]) -> str | None:
    parsed = parse_kubectl_args(args)
    if parsed is None:
        return KUBECTL_ARGS_AMBIGUOUS
    if parsed.leaf not in _SECRET_READ_LEAVES:
        return None
    typed = _typed_words(parsed.positionals)
    if any(_names_kind(word, _SECRET_RESOURCES) for word in typed):
        return KUBECTL_SECRET_READ_REFUSED
    if any(_names_kind(word, _CONFIGMAP_RESOURCES) for word in typed):
        if parsed.leaf == "describe":
            return KUBECTL_SECRET_READ_REFUSED
        formats = {value.split("=", 1)[0] for name, value in parsed.values if name == "output"}
        if formats & _DATA_OUTPUT_FORMATS:
            return KUBECTL_SECRET_READ_REFUSED
    return None


def _names_secrets(word: str) -> bool:
    for part in str(word).split(","):
        kind = part.split("/", 1)[0].split(".", 1)[0].strip().lower()
        if kind in _SECRET_RESOURCES:
            return True
    return False


def kubectl_scope_refusal(args: Sequence[str], *, namespace: str | None) -> str | None:
    if not namespace:
        return None
    parsed = parse_kubectl_args(args)
    if parsed is None:
        return KUBECTL_ARGS_AMBIGUOUS
    if "all-namespaces" in parsed.flags:
        return KUBECTL_ALL_NAMESPACES_OUT_OF_SCOPE
    if any(name == "namespace" and value != namespace for name, value in parsed.values):
        return NAMESPACE_OUT_OF_SCOPE
    if parsed.leaf in _SECRET_READ_LEAVES and parsed.positionals:
        typed = [parsed.positionals[0], *[word for word in parsed.positionals[1:] if "/" in word]]
        if any(_names_secrets(word) for word in typed):
            return SECRET_READ_OUT_OF_SCOPE
    return None


def kubectl_command(
    binary: str,
    args: Sequence[str],
    *,
    kubeconfig: str | None = None,
    kube_context: str | None = None,
    namespace: str | None = None,
) -> list[str]:
    command = [binary]
    if kubeconfig:
        command.extend(["--kubeconfig", kubeconfig])
    if kube_context:
        command.extend(["--context", kube_context])
    if namespace:
        command.extend(["-n", namespace])
    command.extend(str(arg) for arg in args)
    return command
