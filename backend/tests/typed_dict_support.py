from __future__ import annotations

import types
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints, is_typeddict


def shape_problems(value: Any, hint: Any, where: str = "value") -> list[str]:
    origin = get_origin(hint)
    if hint is Any or hint is object:
        return []
    if is_typeddict(hint):
        if not isinstance(value, dict):
            return [f"{where}: {value!r} is no dict"]
        hints = get_type_hints(hint)
        found = [f"{where}.{key}: not in {hint.__name__}" for key in value if key not in hints]
        found += [f"{where}.{key}: missing" for key in hint.__required_keys__ if key not in value]
        for key in hints.keys() & value.keys():
            found += shape_problems(value[key], hints[key], f"{where}.{key}")
        return found
    if origin is Literal:
        return [] if value in get_args(hint) else [f"{where}: {value!r} not in {get_args(hint)}"]
    if origin in (Union, types.UnionType):
        options = [shape_problems(value, option, where) for option in get_args(hint)]
        return [] if any(not found for found in options) else [f"{where}: {value!r} fits no option of {hint}"]
    if origin in (list, tuple):
        if not isinstance(value, origin):
            return [f"{where}: {value!r} is no {origin.__name__}"]
        return [line for index, entry in enumerate(value)
                for line in shape_problems(entry, get_args(hint)[0], f"{where}[{index}]")]
    if origin is dict:
        if not isinstance(value, dict):
            return [f"{where}: {value!r} is no dict"]
        key_hint, value_hint = get_args(hint)
        return [line for key, entry in value.items() for line in (
            shape_problems(key, key_hint, f"{where} key {key!r}") + shape_problems(entry, value_hint, f"{where}.{key}"))]
    if hint is type(None):
        return [] if value is None else [f"{where}: {value!r} is not None"]
    return [] if isinstance(value, hint) and not (hint is int and isinstance(value, bool)) else [
        f"{where}: {value!r} is no {hint.__name__}"]
