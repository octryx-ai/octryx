"""Governed LiteLLM gateway client adapter.

Octryx keeps policy, alias admission, credential, budget, audit, and
failure-semantics ownership; the cluster LiteLLM service is the model data
plane. This package is a client for that data plane — it does not proxy,
load-balance, or route upstream models, and it never exposes an upstream
provider or model identifier to an agent or a user.
"""

from .alias_catalog import (
    GATEWAY_CAPABILITIES,
    GATEWAY_CONFIG_KEY,
    AliasAdmission,
    AliasEntry,
    admitted_alias_entries,
    resolve_alias_admission,
)
from .capability_evidence import PROBE_EVIDENCE_CACHE, ProbeEvidence, ProbeEvidenceCache
from .client import GatewayChatResult, LiteLLMGatewayHttpClient
from .config import LiteLLMGatewayConfig, ProbeContract, build_gateway_config
from .content_logging import ContentLoggingPosture, resolve_content_logging_posture
from .endpoint import GatewayEndpoint, validate_gateway_endpoint
from .errors import GATEWAY_STATES, LiteLLMGatewayError
from .evidence import build_call_evidence, build_denial_evidence
from .evidence_writer import EvidenceWriteDeniedError, write_qualification_evidence
from .network_path import NetworkPathContract, build_network_path_contract
from .policy import (
    MODEL_POLICY_CONFIG_KEY,
    ModelAliasAccessDecision,
    model_alias_access_decision,
)
from .project_admission import (
    PROJECT_ADMISSION_KWARG,
    UNVERIFIED_PROJECT_ADMISSION,
    ProjectModelAdmission,
    build_project_model_admission,
)
from .qualification import FailClosedExpectation, qualify_fail_closed, run_alias_qualification
from .qualification_report import QualificationCheck, QualificationReport, build_qualification_report
from .readiness import gateway_configuration_reason
from .runtime_admission import (
    ADMISSION_DENIAL_KEY,
    LITELLM_GATEWAY_DRIVER,
    admit_gateway_runtimes,
    apply_model_policy_to_runtimes,
)
from .transport_decisions import TransportPolicy
from .transport_policy import resolve_transport_policy

__all__ = [
    "ADMISSION_DENIAL_KEY",
    "GATEWAY_CAPABILITIES",
    "GATEWAY_CONFIG_KEY",
    "GATEWAY_STATES",
    "LITELLM_GATEWAY_DRIVER",
    "MODEL_POLICY_CONFIG_KEY",
    "PROJECT_ADMISSION_KWARG",
    "PROBE_EVIDENCE_CACHE",
    "UNVERIFIED_PROJECT_ADMISSION",
    "AliasAdmission",
    "AliasEntry",
    "ContentLoggingPosture",
    "EvidenceWriteDeniedError",
    "FailClosedExpectation",
    "GatewayChatResult",
    "GatewayEndpoint",
    "LiteLLMGatewayConfig",
    "ProjectModelAdmission",
    "LiteLLMGatewayError",
    "LiteLLMGatewayHttpClient",
    "ModelAliasAccessDecision",
    "NetworkPathContract",
    "ProbeContract",
    "ProbeEvidence",
    "ProbeEvidenceCache",
    "admit_gateway_runtimes",
    "QualificationCheck",
    "QualificationReport",
    "TransportPolicy",
    "admitted_alias_entries",
    "build_project_model_admission",
    "apply_model_policy_to_runtimes",
    "build_call_evidence",
    "build_denial_evidence",
    "build_gateway_config",
    "build_network_path_contract",
    "build_qualification_report",
    "gateway_configuration_reason",
    "model_alias_access_decision",
    "qualify_fail_closed",
    "resolve_alias_admission",
    "resolve_content_logging_posture",
    "resolve_transport_policy",
    "run_alias_qualification",
    "validate_gateway_endpoint",
    "write_qualification_evidence",
]
