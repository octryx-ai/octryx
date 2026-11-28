"""What ast-grep reads per language for the context pack: definitions, calls, imports. A new language is a new row."""

from __future__ import annotations

from typing import Any

# kind -> the field holding the name; "value_kind" narrows a binding to one whose value is a function.
LANGUAGES: dict[str, dict[str, Any]] = {
    "python": {
        "extensions": (".py",),
        "definitions": {"function_definition": "name", "class_definition": "name"},
        "calls": {"call": "function"},
        "imports": ("import_statement", "import_from_statement"),
    },
    "typescript": {
        "extensions": (".ts", ".mts", ".cts"),
        "definitions": {"function_declaration": "name", "class_declaration": "name", "method_definition": "name",
                        "interface_declaration": "name"},
        "arrow_bindings": True,
        "calls": {"call_expression": "function"},
        "imports": ("import_statement",),
    },
    "tsx": {
        "extensions": (".tsx",),
        "definitions": {"function_declaration": "name", "class_declaration": "name", "method_definition": "name"},
        "arrow_bindings": True,
        "calls": {"call_expression": "function"},
        "imports": ("import_statement",),
    },
    "javascript": {
        "extensions": (".js", ".jsx", ".mjs", ".cjs"),
        "definitions": {"function_declaration": "name", "class_declaration": "name", "method_definition": "name"},
        "arrow_bindings": True,
        "calls": {"call_expression": "function"},
        "imports": ("import_statement",),
    },
    "java": {
        "extensions": (".java",),
        "definitions": {"class_declaration": "name", "interface_declaration": "name", "method_declaration": "name"},
        "calls": {"method_invocation": "name"},
        "imports": ("import_declaration",),
    },
    "go": {
        "extensions": (".go",),
        "definitions": {"function_declaration": "name", "method_declaration": "name", "type_spec": "name"},
        "calls": {"call_expression": "function"},
        "imports": ("import_spec",),
    },
    "rust": {
        "extensions": (".rs",),
        "definitions": {"function_item": "name", "struct_item": "name", "enum_item": "name", "trait_item": "name"},
        "calls": {"call_expression": "function"},
        "imports": ("use_declaration",),
    },
    "csharp": {
        "extensions": (".cs",),
        "definitions": {"class_declaration": "name", "interface_declaration": "name", "method_declaration": "name"},
        "calls": {"invocation_expression": "function"},
        "imports": ("using_directive",),
    },
    "ruby": {
        "extensions": (".rb",),
        "definitions": {"method": "name", "class": "name", "module": "name"},
        "calls": {"call": "method"},
        "imports": (),
    },
    "php": {
        "extensions": (".php",),
        "definitions": {"function_definition": "name", "class_declaration": "name", "method_declaration": "name"},
        "calls": {"function_call_expression": "function", "member_call_expression": "name"},
        "imports": ("namespace_use_declaration",),
    },
}
EXTENSIONS: dict[str, str] = {suffix: language for language, row in LANGUAGES.items() for suffix in row["extensions"]}


def _rule(rule_id: str, language: str, body: str) -> str:
    return f"id: {rule_id}\nlanguage: {language}\nrule:\n{body}"


def rules(languages: set[str]) -> str:
    found: list[str] = []
    for language in sorted(languages & set(LANGUAGES)):
        row = LANGUAGES[language]
        for kind, field in row["definitions"].items():
            found.append(_rule(f"def:{kind}", language,
                               f"  kind: {kind}\n  has:\n    field: {field}\n    pattern: $NAME\n"))
        if row.get("arrow_bindings"):
            found.append(_rule("def:arrow", language, "  kind: variable_declarator\n  all:\n    - has:\n"
                                                      "        field: name\n        pattern: $NAME\n    - has:\n"
                                                      "        field: value\n        kind: arrow_function\n"))
        for kind, field in row["calls"].items():
            found.append(_rule(f"call:{kind}", language,
                               f"  kind: {kind}\n  has:\n    field: {field}\n    pattern: $CALLEE\n"))
        for kind in row["imports"]:
            found.append(_rule(f"import:{kind}", language, f"  kind: {kind}\n"))
    return "\n---\n".join(found)


__all__ = ["EXTENSIONS", "LANGUAGES", "rules"]
