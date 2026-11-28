"""Graph extraction profiles as validated data (``profiles/*.json``). A profile is data, not code."""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model

PROFILE_DIR = Path(__file__).parent / "profiles"
REVISIONS_VERSIONED_PRODUCT = "versioned_product"
REVISIONS_ANY = "any"
_REVISION_CLASSES = (REVISIONS_VERSIONED_PRODUCT, REVISIONS_ANY)
_KEY = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
_EDGE_NAME = re.compile(r"^[A-Z][A-Z_]{0,38}[A-Z]$")
_MODEL = re.compile(r"^[A-Z][A-Za-z0-9]{0,59}$")
_PRODUCT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,59}$")
_PLACEHOLDERS = frozenset({"product", "version"})
_PROFILE_FIELDS = frozenset({"key", "version", "title", "applies_to", "self_check", "edge_types", "instructions"})
_APPLIES_FIELDS = frozenset({"revisions", "products"})
_EDGE_FIELDS = frozenset({"name", "model", "action_required", "description"})
MAX_EDGE_TYPES = 30
MAX_DESCRIPTION_CHARS = 1200
MAX_INSTRUCTION_LINES = 40
MAX_INSTRUCTION_LINE_CHARS = 1000


class ExtractionProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EdgeTypeDefinition:
    name: str
    model: str
    description: str
    action_required: bool


@dataclass(frozen=True, slots=True)
class ExtractionProfile:
    key: str
    version: int
    title: str
    revisions: str
    products: tuple[str, ...]
    self_check: bool
    edge_type_definitions: tuple[EdgeTypeDefinition, ...]
    instructions_template: str | None
    # Graphiti's custom fact types: name -> a field-free model whose docstring is the description.
    # Built once per profile, so every extraction passes the same object. ``None`` without types.
    edge_types: dict[str, type[BaseModel]] | None = field(default=None, compare=False)

    @property
    def profile_id(self) -> str:
        return f"{self.key}-v{self.version}"

    @property
    def action_required_types(self) -> frozenset[str]:
        return frozenset(item.name for item in self.edge_type_definitions if item.action_required)

    def applies_to(self, products: tuple[str, ...], version: str | None) -> bool:
        if self.revisions == REVISIONS_VERSIONED_PRODUCT and not (products and version):
            return False
        return not self.products or (bool(products) and products[0] in self.products)

    def instructions(self, product: str, version: str | None) -> str | None:
        if self.instructions_template is None:
            return None
        return self.instructions_template.format(product=product, version=version)


def _refuse(path: Path, rule: str) -> ExtractionProfileError:
    return ExtractionProfileError(f"extraction profile {path.name}: {rule}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ExtractionProfileError("duplicate JSON key")
    return dict(pairs)


def _fields(path: Path, raw: object, expected: frozenset[str], what: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != expected:
        raise _refuse(path, f"{what} must have exactly the fields {sorted(expected)}")
    return raw


def _template(path: Path, lines: object) -> str | None:
    if lines is None:
        return None
    if (
        not isinstance(lines, list)
        or not 0 < len(lines) <= MAX_INSTRUCTION_LINES
        or not all(isinstance(line, str) and 0 < len(line) <= MAX_INSTRUCTION_LINE_CHARS for line in lines)
    ):
        raise _refuse(path, "instructions must be a bounded list of non-empty lines or null")
    template = "\n".join(lines)
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError:
        raise _refuse(path, "instructions have an unbalanced brace") from None
    for _, name, spec, conversion in parsed:
        if name is not None and (name not in _PLACEHOLDERS or spec or conversion):
            raise _refuse(path, "instructions may only use the placeholders {product} and {version}")
    return template


def _edge_type(path: Path, raw: object) -> EdgeTypeDefinition:
    item = _fields(path, raw, _EDGE_FIELDS, "an edge type")
    name, model, description = item["name"], item["model"], item["description"]
    if not isinstance(name, str) or not _EDGE_NAME.fullmatch(name):
        raise _refuse(path, "an edge type name must be UPPER_SNAKE_CASE")
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise _refuse(path, f"edge type {name} needs a CamelCase model name")
    if not isinstance(description, str) or not 0 < len(description.strip()) <= MAX_DESCRIPTION_CHARS:
        raise _refuse(path, f"edge type {name} needs a bounded description")
    if type(item["action_required"]) is not bool:
        raise _refuse(path, f"edge type {name} needs a boolean action_required")
    return EdgeTypeDefinition(name, model, description, item["action_required"])


def _graphiti_types(definitions: tuple[EdgeTypeDefinition, ...]) -> dict[str, type[BaseModel]] | None:
    if not definitions:
        return None
    # No fields on purpose: a field would cost Graphiti one more model call per fact.
    return {item.name: create_model(item.model, __doc__=item.description) for item in definitions}


def load_profile(path: Path) -> ExtractionProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except ExtractionProfileError as error:
        raise _refuse(path, str(error)) from None
    except (OSError, ValueError):
        raise _refuse(path, "not a readable JSON document") from None
    profile = _fields(path, raw, _PROFILE_FIELDS, "a profile")
    key, version, title = profile["key"], profile["version"], profile["title"]
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise _refuse(path, "key must be lower-case kebab-case")
    if type(version) is not int or not 1 <= version <= 999:
        raise _refuse(path, "version must be an integer from 1 to 999")
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 120:
        raise _refuse(path, "title must be a short text")
    applies = _fields(path, profile["applies_to"], _APPLIES_FIELDS, "applies_to")
    products = applies["products"]
    if applies["revisions"] not in _REVISION_CLASSES:
        raise _refuse(path, f"applies_to.revisions must be one of {list(_REVISION_CLASSES)}")
    if not isinstance(products, list) or not all(isinstance(p, str) and _PRODUCT.fullmatch(p) for p in products):
        raise _refuse(path, "applies_to.products must be a list of product keys")
    if len(products) != len(set(products)):
        raise _refuse(path, "applies_to.products has a duplicate")
    if not isinstance(profile["edge_types"], list) or len(profile["edge_types"]) > MAX_EDGE_TYPES:
        raise _refuse(path, "edge_types must be a bounded list")
    definitions = tuple(_edge_type(path, item) for item in profile["edge_types"])
    for attribute in ("name", "model"):
        if len({getattr(item, attribute) for item in definitions}) != len(definitions):
            raise _refuse(path, f"edge types have a duplicate {attribute}")
    if type(profile["self_check"]) is not bool:
        raise _refuse(path, "self_check must be a boolean")
    template = _template(path, profile["instructions"])
    versioned = applies["revisions"] == REVISIONS_VERSIONED_PRODUCT
    if profile["self_check"] and not (definitions and versioned):
        raise _refuse(path, "the self-check needs edge types and versioned product revisions")
    if template is not None and "{version}" in template and not versioned:
        raise _refuse(path, "the {version} placeholder needs versioned product revisions")
    return ExtractionProfile(
        key=key,
        version=version,
        title=title,
        revisions=applies["revisions"],
        products=tuple(products),
        self_check=profile["self_check"],
        edge_type_definitions=definitions,
        instructions_template=template,
        edge_types=_graphiti_types(definitions),
    )


def _specificity(profile: ExtractionProfile) -> tuple[int, int]:
    return (0 if profile.products else 1, 0 if profile.revisions == REVISIONS_VERSIONED_PRODUCT else 1)


def build_catalog(paths: list[Path]) -> dict[str, ExtractionProfile]:
    profiles = [load_profile(path) for path in sorted(paths)]
    catalog: dict[str, ExtractionProfile] = {}
    for path, profile in zip(sorted(paths), profiles, strict=True):
        if any(item.key == profile.key for item in catalog.values()):
            raise _refuse(path, f"profile key {profile.key} is defined twice")
        for other in catalog.values():
            same_class = other.revisions == profile.revisions
            overlapping = (not other.products and not profile.products) or set(other.products) & set(profile.products)
            if same_class and overlapping:
                raise _refuse(path, f"it claims the same revisions as {other.profile_id}")
        catalog[profile.profile_id] = profile
    if not any(item.revisions == REVISIONS_ANY and not item.products for item in profiles):
        raise ExtractionProfileError("extraction profiles: no profile applies to every revision")
    ordered = sorted(catalog.values(), key=lambda item: (_specificity(item), item.profile_id))
    return {item.profile_id: item for item in ordered}


@cache
def extraction_profiles() -> dict[str, ExtractionProfile]:
    return build_catalog(list(PROFILE_DIR.glob("*.json")))


def select_profile(
    products: tuple[str, ...], version: str | None, catalog: dict[str, ExtractionProfile] | None = None
) -> ExtractionProfile:
    profiles = extraction_profiles() if catalog is None else catalog
    return next(profile for profile in profiles.values() if profile.applies_to(tuple(products), version))


__all__ = [
    "PROFILE_DIR",
    "REVISIONS_ANY",
    "REVISIONS_VERSIONED_PRODUCT",
    "EdgeTypeDefinition",
    "ExtractionProfile",
    "ExtractionProfileError",
    "build_catalog",
    "extraction_profiles",
    "load_profile",
    "select_profile",
]
