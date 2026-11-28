"""Provider driver catalog: a provider row names its driver by its exact id."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderDriverSpec:
    driver: str
    provider_family: str
    runtime_kind: str
    default_name: str
    display_name: str
    default_auth_mode: str = "api_key"
    supports_model_sync: bool = True
    supports_tools: bool = True
    # Whether the driver targets a caller-supplied gateway and therefore needs an
    # explicit endpoint_url/base_url before it can be instantiated.
    requires_endpoint_url: bool = False
    # Short admin-facing hint describing the fields this driver expects. Rendered
    # by the provider-drivers catalog so operators know what to fill in.
    config_hint: str = ""


DRIVER_SPECS: dict[str, ProviderDriverSpec] = {
    # Every model call goes through LiteLLM: the bundled one (``model_gateway/bundled_litellm``) or an external one.
    "litellm_gateway": ProviderDriverSpec(
        driver="litellm_gateway",
        provider_family="litellm",
        runtime_kind="api",
        default_name="litellm_gateway",
        display_name="LiteLLM Gateway (governed)",
        requires_endpoint_url=True,
        config_hint=(
            "Governed client for an existing LiteLLM service. Provide the base "
            "URL (endpoint_url), store the virtual key as a Secret Reference, "
            "and declare config_json.litellm_gateway with host_allowlist, "
            "probe_contract, tls (an explicit absolute ca_bundle_path for "
            "private_ca_bundle / public_ca_bundle, plaintext_loopback, or "
            "plaintext_cluster_internal for an http *.svc.cluster.local Service "
            "with attested node_encryption, attested_on and attestation_reference), "
            "content_logging (no prompt, response, credential or header "
            "retention, attested), an optional governed proxy, and the "
            "Octryx alias catalog. Ambient HTTP(S)_PROXY and SSL_CERT_* "
            "variables are never used. Aliases are deny-by-default and must also "
            "be granted per project via the project model_policy."
        ),
    ),
}

SUPPORTED_DRIVERS_MESSAGE = "Supported: " + ", ".join(DRIVER_SPECS) + "."


def get_driver_spec(driver: str | None) -> ProviderDriverSpec | None:
    return DRIVER_SPECS.get(str(driver or "").strip().lower())


def serialize_driver_spec(spec: ProviderDriverSpec) -> dict[str, Any]:
    return asdict(spec)


def list_driver_specs() -> list[dict[str, Any]]:
    return [serialize_driver_spec(spec) for spec in DRIVER_SPECS.values()]


def list_supported_driver_names() -> list[str]:
    """The closed set of driver ids this deployment can actually construct."""

    return sorted(DRIVER_SPECS)


def infer_provider_runtime(
    *,
    driver: str | None,
    name: str | None = None,
    provider_family: str | None = None,
    runtime_kind: str | None = None,
    auth_mode: str | None = None,
) -> dict[str, str]:
    """Resolve a provider's runtime fields from its driver id; `name` is only the row's label."""

    spec = get_driver_spec(driver)
    normalized_name = str(name or "").strip().lower()
    if spec is None:
        return {
            "name": normalized_name,
            "driver": "",
            "provider_family": str(provider_family or "").strip().lower(),
            "runtime_kind": str(runtime_kind or "").strip().lower(),
            "auth_mode": str(auth_mode or "").strip().lower() or "api_key",
        }
    return {
        "name": normalized_name or spec.default_name,
        "driver": spec.driver,
        "provider_family": str(provider_family or "").strip().lower() or spec.provider_family,
        "runtime_kind": str(runtime_kind or "").strip().lower() or spec.runtime_kind,
        "auth_mode": str(auth_mode or "").strip().lower() or spec.default_auth_mode,
    }


def provider_supports_model_sync(*, driver: str | None) -> bool:
    spec = get_driver_spec(driver)
    return bool(spec is not None and spec.supports_model_sync)
