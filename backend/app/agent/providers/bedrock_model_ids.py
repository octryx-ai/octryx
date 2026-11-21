"""The model id the Bedrock Converse API is called with.

A bare foundation model id is turned into a cross-region inference profile id (``eu.``/``us.``/...
prefix) only when the Bedrock model catalog says the model is served through inference profiles.
The catalog fact is ``inferenceTypesSupported`` of ``ListFoundationModels``:

- an ARN (foundation model, inference profile, provisioned throughput, imported model) is used
  exactly as configured, never prefixed;
- an id that already carries a profile prefix is used as configured;
- a model the catalog lists as ``ON_DEMAND`` only (e.g. Qwen) is used as configured, because Bedrock
  has no inference profile for it and a prefixed id is refused;
- every other model (``INFERENCE_PROFILE`` listed, or the catalog fact unknown) keeps the existing
  behaviour: the region's profile prefix.

The catalog is read once per region and cached for the process (``CATALOG_TTL_SECONDS``). The read
is bounded (``CATALOG_CLIENT_CONFIG``: 3 s connect, 5 s read, one attempt) and single-flight: one
read per region at a time, every concurrent caller (any event loop) awaits it. A failed read leaves
the existing prefix rule in place and is retried only after ``FAILED_READ_TTL_SECONDS`` (5 min).
No credential or response text is logged.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

ON_DEMAND = "ON_DEMAND"
INFERENCE_PROFILE = "INFERENCE_PROFILE"
CATALOG_TTL_SECONDS = 3600.0
FAILED_READ_TTL_SECONDS = 300.0
PROFILE_PREFIXES = ("eu.", "us.", "ap.", "apac.", "global.")
REGION_PREFIX_MAP = {
    "eu-central-1": "eu",
    "eu-west-1": "eu",
    "eu-west-2": "eu",
    "eu-west-3": "eu",
    "eu-north-1": "eu",
    "us-east-1": "us",
    "us-west-2": "us",
    "ap-southeast-1": "ap",
    "ap-northeast-1": "ap",
}

InferenceTypes = frozenset[str]

# region -> (expires_at, {model_id: inference types}); an empty map is a failed read.
_CATALOG: dict[str, tuple[float, dict[str, InferenceTypes]]] = {}
# region -> the one catalog read in flight; guarded by ``_LOCK`` (callers may run on different loops).
_IN_FLIGHT: dict[str, Future] = {}
_LOCK = threading.Lock()
_READER = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bedrock-catalog")

# The control-plane read must never hold a chat turn: short timeouts, no botocore retries.
CATALOG_CONNECT_TIMEOUT_SECONDS = 3
CATALOG_READ_TIMEOUT_SECONDS = 5
CATALOG_MAX_ATTEMPTS = 1


def catalog_client_config() -> Any:
    from botocore.config import Config

    return Config(
        connect_timeout=CATALOG_CONNECT_TIMEOUT_SECONDS,
        read_timeout=CATALOG_READ_TIMEOUT_SECONDS,
        retries={"max_attempts": CATALOG_MAX_ATTEMPTS},
    )


def list_foundation_model_summaries(client_kwargs: Mapping[str, Any]) -> list[Any]:
    """``ListFoundationModels`` over a bounded ``bedrock`` control-plane client (blocking)."""
    import boto3

    bedrock = boto3.client("bedrock", config=catalog_client_config(), **dict(client_kwargs))
    return list(bedrock.list_foundation_models().get("modelSummaries") or [])


def is_arn(model: str) -> bool:
    return str(model or "").strip().lower().startswith("arn:")


def is_configured_as_is(model: str) -> bool:
    """An ARN or an id that already names an inference profile: never rewritten."""
    return is_arn(model) or str(model or "").strip().lower().startswith(PROFILE_PREFIXES)


def inference_types_of(summary: Mapping[str, Any]) -> InferenceTypes:
    raw = summary.get("inferenceTypesSupported")
    if not isinstance(raw, list | tuple):
        return frozenset()
    return frozenset(str(item).strip().upper() for item in raw if str(item).strip())


def catalog_from_summaries(summaries: Iterable[Any]) -> dict[str, InferenceTypes]:
    catalog: dict[str, InferenceTypes] = {}
    for summary in summaries:
        if isinstance(summary, Mapping) and summary.get("modelId"):
            catalog[str(summary["modelId"]).strip()] = inference_types_of(summary)
    return catalog


def is_on_demand_only(inference_types: InferenceTypes | None) -> bool:
    return bool(inference_types) and ON_DEMAND in inference_types and INFERENCE_PROFILE not in inference_types


def resolve_bedrock_model_id(model: str, *, region: str, inference_types: InferenceTypes | None = None) -> str:
    """The Converse ``modelId`` for ``model``; see the module docstring for the rules."""
    if is_configured_as_is(model) or is_on_demand_only(inference_types):
        return model
    prefix = REGION_PREFIX_MAP.get(region, "eu")
    return f"{prefix}.{model}"


def _read_catalog(region: str, list_summaries: Callable[[], list[Any]]) -> dict[str, InferenceTypes]:
    try:
        catalog = catalog_from_summaries(list_summaries())
    except Exception as exc:  # noqa: BLE001 - an unreadable catalog keeps the existing behaviour
        logger.warning("Bedrock model catalog unreadable: region=%s error=%s", region, type(exc).__name__)
        catalog = {}
    ttl = CATALOG_TTL_SECONDS if catalog else FAILED_READ_TTL_SECONDS
    with _LOCK:
        _CATALOG[region] = (time.monotonic() + ttl, catalog)
        _IN_FLIGHT.pop(region, None)
    return catalog


async def catalog_inference_types(
    region: str, model: str, list_summaries: Callable[[], list[Any]]
) -> InferenceTypes | None:
    """The catalog's inference types of ``model`` in ``region``; ``None`` when not known.

    ``list_summaries`` performs the blocking ``ListFoundationModels`` read and returns its
    ``modelSummaries``; it runs on the catalog reader thread, only when the cached catalog expired
    and no read for the region is already in flight.
    """
    if is_configured_as_is(model):
        return None
    with _LOCK:
        cached = _CATALOG.get(region)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1].get(model.strip())
        read = _IN_FLIGHT.get(region)
        if read is None or read.cancelled():
            read = _READER.submit(_read_catalog, region, list_summaries)
            _IN_FLIGHT[region] = read
    # Shielded: one caller's cancellation never cancels the read the others await.
    catalog = await asyncio.shield(asyncio.wrap_future(read))
    return catalog.get(model.strip())


def clear_catalog_cache() -> None:
    with _LOCK:
        _CATALOG.clear()
        _IN_FLIGHT.clear()


__all__ = [
    "INFERENCE_PROFILE",
    "ON_DEMAND",
    "REGION_PREFIX_MAP",
    "catalog_client_config",
    "catalog_from_summaries",
    "catalog_inference_types",
    "clear_catalog_cache",
    "inference_types_of",
    "is_arn",
    "is_configured_as_is",
    "is_on_demand_only",
    "list_foundation_model_summaries",
    "resolve_bedrock_model_id",
]
