"""Validate the products and the subject version a revision is about.

Product keys are short, lower-case slugs (``acme-orders``, ``data-platform``, ``spring-boot``);
versions are short tokens (``4.0``, ``2.3.1``, ``2026.1-rc2``). Both are data the platform stores and
filters on, so anything else is refused rather than cleaned up.
"""

from __future__ import annotations

import re

from ..ledger.errors import InvalidEvidenceRequestError

MAX_PRODUCTS = 8
_PRODUCT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,39}$")


def normalize_products(raw: object) -> tuple[str, ...]:
    """A comma-separated string or a list of product keys, deduplicated in order; ``()`` when empty."""
    if raw is None:
        return ()
    if type(raw) is str:
        items = [item.strip() for item in raw.split(",")]
    elif type(raw) in (list, tuple) and all(type(item) is str for item in raw):
        items = [item.strip() for item in raw]
    else:
        raise InvalidEvidenceRequestError()
    products = tuple(dict.fromkeys(item.lower() for item in items if item))
    if len(products) > MAX_PRODUCTS or not all(_PRODUCT.fullmatch(product) for product in products):
        raise InvalidEvidenceRequestError()
    return products


def normalize_version(raw: object) -> str | None:
    if raw is None or (type(raw) is str and not raw.strip()):
        return None
    if type(raw) is not str or not _VERSION.fullmatch(raw.strip()):
        raise InvalidEvidenceRequestError()
    return raw.strip()


__all__ = ["MAX_PRODUCTS", "normalize_products", "normalize_version"]
