"""kubectl argv parsed the way kubectl (cobra/pflag) parses it, for the read-only decision."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

# Persistent flags that choose where or as whom kubectl talks, or write local files.
CONNECTION_OVERRIDE_FLAGS: frozenset[str] = frozenset({
    "as", "as-group", "as-uid", "cache-dir", "certificate-authority", "client-certificate", "client-key",
    "cluster", "context", "insecure-skip-tls-verify", "kubeconfig", "password", "profile", "profile-output",
    "server", "tls-server-name", "token", "user", "username",
})

# long name -> takes a value
_GLOBAL_LONG: dict[str, bool] = {
    "namespace": True, "request-timeout": True, "v": True, "vmodule": True, "log-flush-frequency": True,
    "match-server-version": False, "warnings-as-errors": False, "disable-compression": False, "help": False,
    **{name: name != "insecure-skip-tls-verify" for name in CONNECTION_OVERRIDE_FLAGS},
}
# short -> long name
_GLOBAL_SHORT: dict[str, str] = {"n": "namespace", "s": "server", "v": "v", "h": "help"}

_OUTPUT = {"output": True}
_ALL_NS = {"all-namespaces": False}
_LEAF_LONG: dict[str, dict[str, bool]] = {
    "get": {
        **_OUTPUT, **_ALL_NS, "selector": True, "label-columns": True, "field-selector": True, "sort-by": True,
        "template": True, "chunk-size": True, "subresource": True, "watch": False, "watch-only": False,
        "output-watch-events": False, "ignore-not-found": False, "no-headers": False, "show-kind": False,
        "show-labels": False, "show-managed-fields": False, "allow-missing-template-keys": False,
        "server-print": False,
    },
    "describe": {**_ALL_NS, "selector": True, "chunk-size": True, "show-events": False},
    "logs": {
        "container": True, "selector": True, "since": True, "since-time": True, "tail": True, "limit-bytes": True,
        "max-log-requests": True, "pod-running-timeout": True, "follow": False, "previous": False,
        "timestamps": False, "all-containers": False, "all-pods": False, "prefix": False, "ignore-errors": False,
    },
    "top": {
        **_ALL_NS, "selector": True, "sort-by": True, "field-selector": True, "containers": False,
        "no-headers": False, "use-protocol-buffers": False, "show-capacity": False, "sum": False,
    },
    "events": {
        **_OUTPUT, **_ALL_NS, "for": True, "types": True, "chunk-size": True, "template": True, "watch": False,
        "no-headers": False, "allow-missing-template-keys": False, "show-managed-fields": False,
    },
    "explain": {**_OUTPUT, "api-version": True, "recursive": False},
    "api-resources": {
        **_OUTPUT, "api-group": True, "sort-by": True, "verbs": True, "categories": True, "cached": False,
        "namespaced": False, "no-headers": False,
    },
    "api-versions": {},
    "version": {**_OUTPUT, "client": False},
    "cluster-info": {},
    "auth can-i": {**_ALL_NS, "list": False, "no-headers": False, "quiet": False, "subresource": True},
    "auth whoami": {**_OUTPUT},
}
_LEAF_SHORT: dict[str, dict[str, str]] = {
    "get": {"o": "output", "l": "selector", "L": "label-columns", "A": "all-namespaces", "w": "watch"},
    "describe": {"l": "selector", "A": "all-namespaces"},
    "logs": {"c": "container", "l": "selector", "f": "follow", "p": "previous"},
    "top": {"l": "selector", "A": "all-namespaces"},
    "events": {"o": "output", "A": "all-namespaces", "w": "watch"},
    "explain": {"o": "output"},
    "api-resources": {"o": "output"},
    "version": {"o": "output"},
    "auth can-i": {"A": "all-namespaces", "q": "quiet"},
    "auth whoami": {"o": "output"},
}
# Command groups and the read leaves inside them.
_GROUP_LEAVES: dict[str, frozenset[str]] = {"auth": frozenset({"can-i", "whoami"})}
READ_LEAVES: frozenset[str] = frozenset(_LEAF_LONG)


@dataclass
class KubectlArgs:
    path: list[str] = field(default_factory=list)
    leaf: str | None = None
    flags: list[str] = field(default_factory=list)
    positionals: list[str] = field(default_factory=list)
    values: list[tuple[str, str]] = field(default_factory=list)  # (long name, value) of value-taking flags


def _resolve(path: list[str]) -> tuple[str | None, bool]:
    command = path[0]
    if command in _GROUP_LEAVES:
        if len(path) < 2:
            return None, False
        leaf = f"{command} {path[1]}"
        return (leaf, False) if path[1] in _GROUP_LEAVES[command] else (None, True)
    return (command, False) if command in READ_LEAVES else (None, True)


def parse_kubectl_args(args: Sequence[str]) -> KubectlArgs | None:
    parsed = KubectlArgs()
    words = [str(word) for word in args]
    index = 0
    while index < len(words):
        word = words[index]
        long_table = {**_GLOBAL_LONG, **_LEAF_LONG.get(parsed.leaf or "", {})}
        short_table = {**_GLOBAL_SHORT, **_LEAF_SHORT.get(parsed.leaf or "", {})}
        if word == "--":
            return None
        if word.startswith("--"):
            name, has_value, value = word[2:].partition("=")
            if name not in long_table:
                return None
            parsed.flags.append(name)
            if long_table[name] and not has_value:
                if index + 1 >= len(words):
                    return None
                index += 1  # the value, whatever it looks like
                value = words[index]
            if long_table[name]:
                parsed.values.append((name, value))
            index += 1
            continue
        if word.startswith("-") and len(word) > 1:
            cluster = word[1:]
            position = 0
            while position < len(cluster):
                name = short_table.get(cluster[position])
                if name is None:
                    return None
                parsed.flags.append(name)
                rest = cluster[position + 1 :]
                if rest.startswith("="):
                    if long_table[name]:
                        parsed.values.append((name, rest[1:]))
                    break  # ``-n=x``: the rest of the word is the value
                if long_table[name]:
                    if not rest:
                        if index + 1 >= len(words):
                            return None
                        index += 1
                        rest = words[index]
                    parsed.values.append((name, rest))
                    break
                position += 1
            index += 1
            continue
        if parsed.leaf is None:
            parsed.path.append(word)
            leaf, unknown = _resolve(parsed.path)
            if unknown:
                return parsed
            parsed.leaf = leaf
        else:
            parsed.positionals.append(word)
        index += 1
    return parsed


__all__ = ["CONNECTION_OVERRIDE_FLAGS", "KubectlArgs", "READ_LEAVES", "parse_kubectl_args"]
