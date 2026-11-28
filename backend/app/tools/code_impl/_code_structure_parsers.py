"""Deterministic per-language declaration parsers for code structure snapshots."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ._code_structure_terraform import parse_terraform_hcl

# Parser contract: (relative_path, text) ->
#   {package, imports, types:[{name, kind, extends, implements, fields, methods}]}
# Types may additionally carry optional literal-evidence keys the snapshot core
# understands: "uses" (per-type named references), "uses_packages" (package-node
# reference candidates), and "attributes" (extra node attributes, merged in).
LanguageParser = Callable[[str, str], dict[str, Any]]

_LANGUAGE_PARSERS: dict[str, LanguageParser] = {}
LANGUAGE_SUFFIXES: dict[str, tuple[str, ...]] = {}


def register_language_parser(language: str, suffixes: tuple[str, ...], parser: LanguageParser) -> None:
    normalized = str(language or "").strip().lower()
    if not normalized:
        raise ValueError("language is required")
    _LANGUAGE_PARSERS[normalized] = parser
    LANGUAGE_SUFFIXES[normalized] = tuple(suffix.lower() for suffix in suffixes)


def language_for_suffix(suffix: str) -> str:
    normalized = suffix.lower()
    for language, suffixes in LANGUAGE_SUFFIXES.items():
        if normalized in suffixes:
            return language
    return ""


def parse_file_structure(relative_path: str, text: str, language: str) -> dict[str, Any]:
    parser = _LANGUAGE_PARSERS.get(str(language or "").strip().lower())
    if parser is None:
        return {"package": "", "imports": [], "types": []}
    return parser(relative_path, text)


def _strip_comments(text: str, *, line_marker: str = "//") -> list[str]:
    without_blocks = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines = []
    for line in without_blocks.splitlines():
        if line_marker and line_marker in line:
            line = line.split(line_marker, 1)[0]
        lines.append(line)
    return lines


def _split_type_list(raw: str) -> list[str]:
    names: list[str] = []
    depth = 0
    current = ""
    for char in raw:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            names.append(current)
            current = ""
            continue
        if depth == 0 and char not in "<>":
            current += char
    names.append(current)
    cleaned = []
    for name in names:
        base = name.strip().split("<", 1)[0].strip()
        if base:
            cleaned.append(base.rsplit(".", 1)[-1])
    return cleaned


# ── Java ─────────────────────────────────────────────────────────────────────

_JAVA_TYPE_DECL = re.compile(
    r"\b(?:class|interface|enum|record)\s+(\w+)"
)
_JAVA_FIELD = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|transient|volatile)\s+)*"
    r"([A-Za-z_][\w.]*(?:<[^;=]*>)?(?:\[\])*)\s+(\w+)\s*(?:=[^;]*)?;\s*$"
)
_JAVA_METHOD = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|abstract|synchronized|default|native)\s+)*"
    r"(?:<[^>]+>\s*)?([A-Za-z_][\w.]*(?:<[^({]*>)?(?:\[\])*)\s+(\w+)\s*\(([^)]*)\)"
)
_JAVA_KEYWORD_RETURNS = {"new", "return", "if", "while", "for", "switch", "throw", "else", "case", "catch"}


def _java_declaration_text(lines: list[str], start_index: int) -> str:
    collected: list[str] = []
    for offset in range(0, 6):
        if start_index + offset >= len(lines):
            break
        line = lines[start_index + offset]
        collected.append(line)
        if "{" in line or ";" in line:
            break
    return " ".join(part.strip() for part in collected)


def _parse_java(relative_path: str, text: str) -> dict[str, Any]:
    lines = _strip_comments(text)
    package = ""
    imports: list[str] = []
    types: list[dict[str, Any]] = []
    current_type: dict[str, Any] | None = None
    type_depth = 0
    depth = 0
    for index, line in enumerate(lines):
        package_match = re.match(r"^\s*package\s+([\w.]+)\s*;", line)
        if package_match:
            package = package_match.group(1)
            continue
        import_match = re.match(r"^\s*import\s+(?:static\s+)?([\w.]+)(?:\.\*)?\s*;", line)
        if import_match:
            imports.append(import_match.group(1))
            continue
        decl_match = _JAVA_TYPE_DECL.search(line)
        if decl_match and current_type is None and not line.lstrip().startswith(("*", "@")):
            declaration = _java_declaration_text(lines, index)
            kind_match = re.search(r"\b(class|interface|enum|record)\s+(\w+)", declaration)
            if kind_match:
                kind = "class" if kind_match.group(1) == "record" else kind_match.group(1)
                extends_match = re.search(r"\bextends\s+([^{]+?)(?:\bimplements\b|\bpermits\b|\{|$)", declaration)
                implements_match = re.search(r"\bimplements\s+([^{]+?)(?:\bpermits\b|\{|$)", declaration)
                current_type = {
                    "name": kind_match.group(2),
                    "kind": kind,
                    "extends": _split_type_list(extends_match.group(1)) if extends_match else [],
                    "implements": _split_type_list(implements_match.group(1)) if implements_match else [],
                    "fields": [],
                    "methods": [],
                }
                types.append(current_type)
                type_depth = depth
        if current_type is not None and depth == type_depth + 1:
            field_match = _JAVA_FIELD.match(line)
            ctor_match = re.match(r"^\s*(?:(?:public|protected|private)\s+)?(\w+)\s*\(([^)]*)\)", line)
            if field_match and field_match.group(1) not in _JAVA_KEYWORD_RETURNS:
                current_type["fields"].append(f"{field_match.group(2)}: {field_match.group(1)}")
            elif ctor_match and ctor_match.group(1) == current_type["name"]:
                current_type["methods"].append(f"+{ctor_match.group(1)}({_compact_params(ctor_match.group(2))})")
            else:
                method_match = _JAVA_METHOD.match(line)
                if method_match and method_match.group(1) not in _JAVA_KEYWORD_RETURNS:
                    current_type["methods"].append(
                        f"+{method_match.group(2)}({_compact_params(method_match.group(3))}): {method_match.group(1)}"
                    )
        depth += line.count("{") - line.count("}")
        if current_type is not None and depth <= type_depth:
            current_type = None
    return {"package": package, "imports": imports, "types": types}


def _compact_params(raw: str) -> str:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    names = []
    for part in parts:
        tokens = part.split()
        names.append(tokens[-1] if tokens else part)
    return ", ".join(names)


# ── Python ───────────────────────────────────────────────────────────────────


def _parse_python(relative_path: str, text: str) -> dict[str, Any]:
    package = _module_package_from_path(relative_path)
    imports: list[str] = []
    types: list[dict[str, Any]] = []
    current_type: dict[str, Any] | None = None
    for line in text.splitlines():
        import_match = re.match(r"^import\s+([\w.]+)", line)
        if import_match:
            imports.append(import_match.group(1))
            continue
        from_match = re.match(r"^from\s+([\w.]+)\s+import\s+(.+)", line)
        if from_match:
            module = from_match.group(1)
            for item in from_match.group(2).split(","):
                name = item.strip().split(" as ", 1)[0].strip().strip("()")
                if name and name != "*":
                    imports.append(f"{module}.{name}")
            continue
        class_match = re.match(r"^class\s+(\w+)(?:\(([^)]*)\))?\s*:", line)
        if class_match:
            bases = [
                base.strip().split("[", 1)[0].rsplit(".", 1)[-1]
                for base in (class_match.group(2) or "").split(",")
                if base.strip() and "=" not in base
            ]
            current_type = {
                "name": class_match.group(1),
                "kind": "class",
                "extends": [base for base in bases if base and base != "object"],
                "implements": [],
                "fields": [],
                "methods": [],
            }
            types.append(current_type)
            continue
        if line and not line.startswith((" ", "\t")):
            current_type = None
        if current_type is None:
            continue
        method_match = re.match(r"^\s{4}(?:async\s+)?def\s+(\w+)\s*\(([^)]*)", line)
        if method_match:
            params = [
                part.strip().split(":", 1)[0].split("=", 1)[0].strip() for part in method_match.group(2).split(",")
            ]
            params = [param for param in params if param and param not in {"self", "cls"}]
            current_type["methods"].append(f"+{method_match.group(1)}({', '.join(params)})")
            continue
        field_match = re.match(r"^\s{4}(\w+)\s*(?::\s*([^=\n]+?))?\s*(?:=.*)?$", line)
        if field_match and not line.lstrip().startswith(("def ", "@", "#")) and ("=" in line or ":" in line):
            annotation = (field_match.group(2) or "").strip()
            current_type["fields"].append(
                f"{field_match.group(1)}: {annotation}" if annotation else field_match.group(1)
            )
    return {"package": package, "imports": imports, "types": types}


def _module_package_from_path(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


# ── TypeScript / JavaScript ──────────────────────────────────────────────────

_TS_CLASS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)"
    r"(?:<[^>]*>)?(?:\s+extends\s+([\w.]+))?(?:\s+implements\s+([\w,\s.<>]+))?"
)
_TS_INTERFACE = re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)(?:<[^>]*>)?(?:\s+extends\s+([\w,\s.<>]+))?")
_TS_ENUM = re.compile(r"^\s*(?:export\s+)?(?:const\s+)?enum\s+(\w+)")
_TS_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|readonly|static|async|override)\s+)*(\w+)\s*\(([^)]*)\)\s*(?::\s*[^{;]+)?\s*\{"
)
_TS_FIELD = re.compile(r"^\s*(?:(?:public|private|protected|readonly|static)\s+)*(\w+)\s*[?!]?\s*:\s*([^=;{(]+)[=;]?")
_TS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "constructor",
    "function", "new", "case", "import", "export", "else", "default",
}


def _parse_typescript(relative_path: str, text: str) -> dict[str, Any]:
    package = _module_package_from_path(relative_path)
    lines = _strip_comments(text)
    imports: list[str] = []
    types: list[dict[str, Any]] = []
    current_type: dict[str, Any] | None = None
    type_depth = 0
    depth = 0
    for line in lines:
        import_match = re.match(r"^\s*import\s+(?:type\s+)?(.+?)\s+from\s+['\"]([^'\"]+)['\"]", line)
        if import_match:
            clause = import_match.group(1)
            for name in re.findall(r"[A-Za-z_]\w*", clause):
                if name not in {"as", "type"}:
                    imports.append(name)
            continue
        if current_type is None:
            declared = None
            class_match = _TS_CLASS.match(line)
            interface_match = _TS_INTERFACE.match(line) if class_match is None else None
            enum_match = _TS_ENUM.match(line) if class_match is None and interface_match is None else None
            if class_match:
                declared = {
                    "name": class_match.group(1),
                    "kind": "class",
                    "extends": _split_type_list(class_match.group(2) or ""),
                    "implements": _split_type_list(class_match.group(3) or ""),
                }
            elif interface_match:
                declared = {
                    "name": interface_match.group(1),
                    "kind": "interface",
                    "extends": _split_type_list(interface_match.group(2) or ""),
                    "implements": [],
                }
            elif enum_match:
                declared = {"name": enum_match.group(1), "kind": "enum", "extends": [], "implements": []}
            if declared is not None:
                current_type = {**declared, "fields": [], "methods": []}
                types.append(current_type)
                type_depth = depth
        elif depth == type_depth + 1:
            method_match = _TS_METHOD.match(line)
            if method_match and method_match.group(1) not in _TS_KEYWORDS:
                params = [
                    part.strip().split(":", 1)[0].strip() for part in method_match.group(2).split(",") if part.strip()
                ]
                current_type["methods"].append(f"+{method_match.group(1)}({', '.join(params)})")
            else:
                field_match = _TS_FIELD.match(line)
                if field_match and field_match.group(1) not in _TS_KEYWORDS and "(" not in line.split(":", 1)[0]:
                    current_type["fields"].append(f"{field_match.group(1)}: {field_match.group(2).strip()}")
        depth += line.count("{") - line.count("}")
        if current_type is not None and depth <= type_depth:
            current_type = None
    return {"package": package, "imports": imports, "types": types}


# ── Rust ─────────────────────────────────────────────────────────────────────


def _parse_rust(relative_path: str, text: str) -> dict[str, Any]:
    package = _module_package_from_path(relative_path)
    lines = _strip_comments(text)
    imports: list[str] = []
    types: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _type_entry(name: str, kind: str) -> dict[str, Any]:
        if name not in types:
            types[name] = {"name": name, "kind": kind, "extends": [], "implements": [], "fields": [], "methods": []}
            order.append(name)
        return types[name]

    current: dict[str, Any] | None = None
    current_mode = ""
    depth = 0
    type_depth = 0
    for line in lines:
        use_match = re.match(r"^\s*use\s+([\w:]+)(?:::\{([^}]*)\})?", line)
        if use_match:
            base = use_match.group(1)
            if use_match.group(2):
                for item in use_match.group(2).split(","):
                    name = item.strip().split(" as ", 1)[0].strip()
                    if name:
                        imports.append(f"{base}::{name}".replace("::", "."))
            else:
                imports.append(base.replace("::", "."))
            continue
        struct_match = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", line)
        enum_match = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", line)
        trait_match = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", line)
        impl_match = re.match(r"^\s*impl(?:<[^>]*>)?\s+(?:([\w:]+)\s+for\s+)?([\w:]+)", line)
        if struct_match and current is None:
            current, current_mode, type_depth = _type_entry(struct_match.group(1), "class"), "struct", depth
        elif enum_match and current is None:
            current, current_mode, type_depth = _type_entry(enum_match.group(1), "enum"), "enum", depth
        elif trait_match and current is None:
            current, current_mode, type_depth = _type_entry(trait_match.group(1), "interface"), "trait", depth
        elif impl_match and current is None:
            target = impl_match.group(2).rsplit("::", 1)[-1].split("<", 1)[0]
            entry = _type_entry(target, "class")
            trait_name = impl_match.group(1)
            if trait_name:
                trait_base = trait_name.rsplit("::", 1)[-1].split("<", 1)[0]
                if trait_base not in entry["implements"]:
                    entry["implements"].append(trait_base)
            current, current_mode, type_depth = entry, "impl", depth
        elif current is not None and depth == type_depth + 1:
            if current_mode == "struct":
                field_match = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(\w+)\s*:\s*([^,]+),?\s*$", line)
                if field_match:
                    current["fields"].append(f"{field_match.group(1)}: {field_match.group(2).strip()}")
            elif current_mode in {"impl", "trait"}:
                fn_match = re.match(
                    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\(([^)]*)", line
                )
                if fn_match:
                    params = [
                        part.strip().split(":", 1)[0].strip()
                        for part in fn_match.group(2).split(",")
                        if part.strip() and not part.strip().startswith(("&", "self", "mut self"))
                    ]
                    current["methods"].append(f"+{fn_match.group(1)}({', '.join(params)})")
        depth += line.count("{") - line.count("}")
        if current is not None and depth <= type_depth:
            if line.strip().endswith(";") and current_mode == "struct" and depth == type_depth:
                # tuple struct `struct Foo(...);` has no body
                pass
            current = None
            current_mode = ""
    return {"package": package, "imports": imports, "types": [types[name] for name in order]}


register_language_parser("java", (".java",), _parse_java)
register_language_parser("python", (".py",), _parse_python)
register_language_parser("typescript", (".ts", ".tsx"), _parse_typescript)
register_language_parser("javascript", (".js", ".jsx"), _parse_typescript)
register_language_parser("rust", (".rs",), _parse_rust)
register_language_parser("terraform", (".tf",), parse_terraform_hcl)
