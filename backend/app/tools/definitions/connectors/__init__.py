"""Tool definitions for connectors domain."""

from __future__ import annotations

import copy

from .aws_assessments import AWS_ASSESSMENT_DEFINITIONS
from .aws_services import AWS_SERVICE_DEFINITIONS
from .aws_topology import AWS_TOPOLOGY_DEFINITIONS
from .azure_gcp import AZURE_GCP_DEFINITIONS
from .cloud_operations import CLOUD_OPERATION_DEFINITIONS
from .incidents import INCIDENT_DEFINITIONS


def get_connectors_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for connectors tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(
        {
            **CLOUD_OPERATION_DEFINITIONS,
            **AWS_TOPOLOGY_DEFINITIONS,
            **AWS_ASSESSMENT_DEFINITIONS,
            **AWS_SERVICE_DEFINITIONS,
            **AZURE_GCP_DEFINITIONS,
            **INCIDENT_DEFINITIONS,
        }
    )
