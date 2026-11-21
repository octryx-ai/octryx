"""Admin provider write boundary: a provider row names one supported driver id.

The runtime constructs a client from the exact driver id only
(`agent/providers/provider_registry.py` DRIVER_SPECS), so a create or update that names
anything else is refused before a row, secret or audit record exists. The refusal never
echoes the submitted value.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...agent.providers import get_driver_spec, list_supported_driver_names

PROVIDER_DRIVER_UNSUPPORTED_CODE = "provider_driver_unsupported"


def require_supported_driver(driver: Any) -> str:
    """Return the canonical driver id, or refuse the request with a bounded 400."""

    spec = get_driver_spec(str(driver or ""))
    if spec is not None:
        return spec.driver
    raise HTTPException(
        status_code=400,
        detail={
            "code": PROVIDER_DRIVER_UNSUPPORTED_CODE,
            "message": "The provider driver is not supported. Choose one of the supported driver ids.",
            "supported_drivers": list_supported_driver_names(),
        },
    )


__all__ = ["PROVIDER_DRIVER_UNSUPPORTED_CODE", "require_supported_driver"]
