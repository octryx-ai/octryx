"""Shared offline fixtures for the governed LiteLLM gateway suites: a stateful recording fake gateway on
``httpx.MockTransport``, so a denial is proven to produce zero dispatches."""

from __future__ import annotations

import atexit
import shutil
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from app.agent.providers.litellm_gateway import LiteLLMGatewayClient
from app.models import LLMModel, LLMProvider
from app.services.model_gateway.data_policy import (
    WorkspaceDataClassification,
    resolve_data_classification,
)
from app.services.model_gateway.litellm import (
    PROJECT_ADMISSION_KWARG,
    ProjectModelAdmission,
    build_project_model_admission,
)
from app.services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache

GATEWAY_HOST = "litellm.internal.test"
BASE_URL = f"https://{GATEWAY_HOST}/v1"
VIRTUAL_KEY = "sk-virtual-key-value-must-never-leak"
ALIAS = "octryx-general"
# The test baseline's runtime (``tests/conftest``): its own provider and alias, so no suite's ``ALIAS`` is ambiguous.
# An active gateway narrows every level's aliases (``model_catalog.clearance``), so the suites here, which build their
# own gateway world, run with it switched off (``without_baseline_runtime``).
BASELINE_ALIAS = "baseline-model"
BASELINE_PROVIDER = "baseline_gateway"
MODEL_GROUP = "general-group"
PROJECT_ID = "project-alpha"
# The default alias is approved for ``internal`` data, so a workspace classified
# ``internal`` is the permitted baseline every suite outside the data-policy tests dispatches under.
WORKSPACE_CLASSIFICATION = "internal"
MESSAGES = [{"role": "user", "content": "hello"}]
TOOLS = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]

GATEWAY_REPORTED_COST = {"source": "gateway_reported", "contract_reference": "cost-contract-2026-09"}
GOVERNED_FREE_COST = {"source": "governed_free", "contract_reference": "free-tier-approval-2026-09"}

# The default alias' catalog prices, per million USD, as model sync persists
# them — and what one 1000-prompt/500-completion turn costs at those prices.
CATALOG_INPUT_PRICE = 1.0
CATALOG_OUTPUT_PRICE = 2.0
CATALOG_TURN_COST = Decimal("0.002000")

DEFAULT_CATALOG = {
    "data": [
        {
            "id": MODEL_GROUP,
            "model_info": {"supports_function_calling": True, "max_input_tokens": 128000},
        }
    ]
}


_CA_BUNDLE_DIRECTORY: Path | None = None
_CA_BUNDLE_PATH: Path | None = None


def write_ca_bundle(path: Path, *, common_name: str = "Octryx Test CA") -> Path:
    key = ed25519.Ed25519PrivateKey.generate()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return path


def shared_ca_bundle_path() -> str:
    global _CA_BUNDLE_DIRECTORY, _CA_BUNDLE_PATH
    if _CA_BUNDLE_PATH is None:
        _CA_BUNDLE_DIRECTORY = Path(tempfile.mkdtemp(prefix="octryx-litellm-test-ca-"))
        atexit.register(shutil.rmtree, _CA_BUNDLE_DIRECTORY, ignore_errors=True)
        _CA_BUNDLE_PATH = write_ca_bundle(_CA_BUNDLE_DIRECTORY / "ca.pem")
    return str(_CA_BUNDLE_PATH)


# Governed transport and posture sections. The suites run against
# ``httpx.MockTransport``, so the egress path is direct: a governed proxy would
# mount a *real* proxy transport and take precedence over the mock. The real
# TLS/proxy path is proven over sockets by ``deployment/local/litellm-gateway/``.
CONTENT_LOGGING_POSTURE = {
    "mode": "no_content_retention",
    "prompt_retention": "disabled",
    "response_retention": "disabled",
    "key_metadata_retention": "disabled",
    "header_retention": "disabled",
    "success_callbacks": [],
    "failure_callbacks": [],
    "attestation_reference": "litellm-posture-2026-09-27",
    "attested_on": "2026-09-27",
    "verified_against": "declared_configuration",
}


def public_bundle_tls() -> dict[str, Any]:
    return {"mode": "public_ca_bundle", "ca_bundle_path": shared_ca_bundle_path()}


def gateway_section(**overrides: Any) -> dict[str, Any]:
    section: dict[str, Any] = {
        "host_allowlist": [GATEWAY_HOST],
        "probe_contract": {
            "models_path": "/models",
            "response_shape": "openai_model_list",
            "model_group_field": "id",
        },
        "tls": public_bundle_tls(),
        "proxy": {"mode": "direct"},
        "content_logging": dict(CONTENT_LOGGING_POSTURE),
        "aliases": {
            ALIAS: {
                "model_group": MODEL_GROUP,
                "context_limit": 128000,
                "data_policy_class": "internal",
                "capabilities": {"tools": True},
                "cost": {
                    "source": "catalog_pricing",
                    "input_per_million_usd": 1.0,
                    "output_per_million_usd": 2.0,
                },
            }
        },
    }
    section.update(overrides)
    return section


def gateway_config(**overrides: Any) -> dict[str, Any]:
    return {"litellm_gateway": gateway_section(**overrides)}


def alias_with_cost(cost: dict[str, Any]) -> dict[str, Any]:
    section = gateway_section()
    section["aliases"][ALIAS]["cost"] = cost
    return {"litellm_gateway": section}


def chat_body(*, model: str = MODEL_GROUP, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "choices": [{"message": {"content": "gateway answer", "tool_calls": None}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }
    body.update(overrides)
    return body


def granted_project_config(*aliases: str) -> dict[str, Any]:
    return {
        "model_policy": {"allowed_aliases": list(aliases or (ALIAS,))},
        "data_policy": {"classification": WORKSPACE_CLASSIFICATION},
    }


def workspace_classification(classification: str = WORKSPACE_CLASSIFICATION) -> WorkspaceDataClassification:
    return resolve_data_classification(project_data_policy={"classification": classification})


def verified_admission(
    *aliases: str,
    classification: str = WORKSPACE_CLASSIFICATION,
) -> ProjectModelAdmission:
    return build_project_model_admission(
        project_id=PROJECT_ID,
        project_config=granted_project_config(*aliases),
        source="test_boundary",
        data_classification=workspace_classification(classification),
    )


def gateway_provider(**overrides: Any) -> LLMProvider:
    values: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": "litellm_gateway",
        "provider_family": "litellm",
        "driver": "litellm_gateway",
        "runtime_kind": "api",
        "auth_mode": "api_key",
        "is_active": True,
        "endpoint_url": BASE_URL,
        "api_key_secret_ref": str(uuid.uuid4()),
        "config_json": gateway_config(),
    }
    values.update(overrides)
    return LLMProvider(**values)


def baseline_gateway_provider() -> LLMProvider:
    section = gateway_section()
    section["aliases"] = {BASELINE_ALIAS: {**section["aliases"][ALIAS], "model_group": BASELINE_ALIAS}}
    return gateway_provider(name=BASELINE_PROVIDER, display_name="LiteLLM (Default)", default_model_id=BASELINE_ALIAS,
                            is_global=True, config_json={"litellm_gateway": section})


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001 - pytest hook signature
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).parent == here:
            item.add_marker(pytest.mark.without_baseline_runtime)


def gateway_runtime(**overrides: Any) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "provider_name": "litellm",
        "driver": "litellm_gateway",
        "model": ALIAS,
        "target_id": "t1",
        "priority": 1,
        "config_json": gateway_config(),
    }
    runtime.update(overrides)
    return runtime


def backup_runtime(**overrides: Any) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "provider_name": "backup",
        "driver": "openrouter_api",
        "model": "backup-model",
        "target_id": "t2",
        "priority": 2,
    }
    runtime.update(overrides)
    return runtime


async def stale_priced_gateway_model(db) -> LLMProvider:
    provider = LLMProvider(id=str(uuid.uuid4()), name="litellm_gateway", driver="litellm_gateway", display_name="LiteLLM", is_active=True)
    db.add_all(
        [
            provider,
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=provider.id,
                model_id=ALIAS,
                pricing_input=CATALOG_INPUT_PRICE,
                pricing_output=CATALOG_OUTPUT_PRICE,
                is_active=True,
            ),
        ]
    )
    await db.commit()
    return provider


class FakeLiteLLMGateway:
    def __init__(
        self,
        *,
        catalog: dict[str, Any] | None = None,
        catalog_status: int = 200,
        chat_status: int = 200,
        chat_payload: dict[str, Any] | None = None,
        chat_content: bytes | None = None,
        response_headers: dict[str, str] | None = None,
    ):
        self.requests: list[httpx.Request] = []
        self.catalog = DEFAULT_CATALOG if catalog is None else catalog
        self.catalog_status = catalog_status
        self.chat_status = chat_status
        self.chat_payload = chat_body() if chat_payload is None else chat_payload
        # A raw chat body, for shapes ``json=`` cannot express: httpx serializes
        # with ``allow_nan=False``, while a real gateway can emit the bare ``NaN``
        # and ``Infinity`` literals that ``json.loads`` accepts by default.
        self.chat_content = chat_content
        self.response_headers = dict(response_headers or {})

    @property
    def chat_requests(self) -> list[httpx.Request]:
        return [item for item in self.requests if item.url.path.endswith("/chat/completions")]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(self.catalog_status, json=self.catalog, headers=self.response_headers)
        if request.url.path.endswith("/chat/completions"):
            if self.chat_content is not None:
                return httpx.Response(
                    self.chat_status,
                    content=self.chat_content,
                    headers={"content-type": "application/json", **self.response_headers},
                )
            return httpx.Response(self.chat_status, json=self.chat_payload, headers=self.response_headers)
        return httpx.Response(404, json={"error": {"code": "not_found"}})


class RecordingRuntimeFactory:
    def __init__(
        self,
        *,
        failures: dict[str, Exception] | None = None,
        forbidden: tuple[str, ...] = (),
    ):
        self.failures = dict(failures or {})
        self.forbidden = set(forbidden)
        self.constructed: list[str] = []
        self.dispatched: list[str] = []
        self.seen_admissions: list[Any] = []

    def __call__(self, **kwargs: Any) -> _RecordingRuntimeClient:
        name = str(kwargs.get("provider_name") or "")
        self.constructed.append(name)
        self.seen_admissions.append(kwargs.get(PROJECT_ADMISSION_KWARG))
        if name in self.forbidden:
            raise AssertionError(f"provider {name!r} must never construct a client")
        return _RecordingRuntimeClient(name, self)


class _RecordingRuntimeClient:
    def __init__(self, name: str, factory: RecordingRuntimeFactory):
        self._name = name
        self._factory = factory

    async def chat(self, **_kwargs: Any) -> dict[str, Any]:
        self._factory.dispatched.append(self._name)
        failure = self._factory.failures.get(self._name)
        if failure is not None:
            raise failure
        return {"content": f"{self._name} answer", "tool_calls": None, "usage": {}}

    async def close(self) -> None:
        return None


@pytest.fixture
def gateway() -> FakeLiteLLMGateway:
    return FakeLiteLLMGateway()


@pytest.fixture
async def build_gateway_client():
    created: list[LiteLLMGatewayClient] = []

    def _build(target: FakeLiteLLMGateway, **overrides: Any) -> LiteLLMGatewayClient:
        kwargs: dict[str, Any] = {
            "endpoint_url": BASE_URL,
            "api_key": VIRTUAL_KEY,
            "config_json": gateway_config(),
            "transport": target.transport(),
            "evidence_cache": ProbeEvidenceCache(),
            "project_admission": verified_admission(ALIAS, "gpt-4o"),
        }
        kwargs.update(overrides)
        client = LiteLLMGatewayClient(**kwargs)
        created.append(client)
        return client

    yield _build

    for client in created:
        await client.close()
