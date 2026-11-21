"""The one import boundary of Graphiti in the product.

Every Graphiti symbol the product uses is imported here and re-exported, so no module can import
``graphiti_core`` before the environment below is set (an import sorter would otherwise move a
direct third-party import ahead of this module).

Graphiti sends anonymous usage telemetry to PostHog **by default** (``GRAPHITI_TELEMETRY_ENABLED``
defaults to true in 0.30.2). The platform sends nothing about a Workspace anywhere it was not told
to, so this module switches telemetry off before ``graphiti_core`` is imported and refuses to
continue if Graphiti still reports it enabled. Every product module imports Graphiti through here.

Graphiti's own loggers log at DEBUG with entity names and facts; they are held at WARNING so no
Workspace content reaches the log stream through them.

Graphiti also calls ``dotenv.load_dotenv()`` at import time (``graphiti_core/graphiti.py``,
``driver/driver.py``, ``helpers.py``). That walks up from the installed package to the first
``.env`` it finds and copies every key into ``os.environ`` of the whole process, where it can override the
process ``DATABASE_URL`` that ``alembic/env.py`` prefers. The product reads configuration only through its
settings, so ``.env`` loading is disabled while Graphiti is imported and the ``PYTHON_DOTENV_DISABLED`` state is
restored afterwards.
"""

from __future__ import annotations

import logging
import os

os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
logging.getLogger("graphiti_core").setLevel(logging.WARNING)

_DOTENV_DISABLED_KEY = "PYTHON_DOTENV_DISABLED"
_dotenv_disabled_before_import = os.environ.get(_DOTENV_DISABLED_KEY)
os.environ[_DOTENV_DISABLED_KEY] = "1"
try:
    from graphiti_core import Graphiti  # noqa: E402
    from graphiti_core.cross_encoder.client import CrossEncoderClient  # noqa: E402
    from graphiti_core.driver.driver import GraphDriver, GraphDriverSession, GraphProvider  # noqa: E402
    from graphiti_core.driver.query_executor import Transaction  # noqa: E402
    from graphiti_core.embedder.client import EmbedderClient  # noqa: E402
    from graphiti_core.errors import NodeNotFoundError  # noqa: E402
    from graphiti_core.graph_queries import get_range_indices  # noqa: E402
    from graphiti_core.graphiti_types import GraphitiClients  # noqa: E402
    from graphiti_core.llm_client.client import LLMClient  # noqa: E402
    from graphiti_core.llm_client.config import LLMConfig, ModelSize  # noqa: E402
    from graphiti_core.nodes import EntityNode, EpisodeType, EpisodicNode  # noqa: E402
    from graphiti_core.prompts.extract_edges import Edge, ExtractedEdges  # noqa: E402
    from graphiti_core.search.search_filters import SearchFilters  # noqa: E402
    from graphiti_core.search.search_utils import edge_fulltext_search, edge_similarity_search  # noqa: E402
    from graphiti_core.telemetry.telemetry import is_telemetry_enabled  # noqa: E402
    from graphiti_core.tracer import NoOpTracer  # noqa: E402
    from graphiti_core.utils.maintenance.edge_operations import extract_edges  # noqa: E402
    from graphiti_core.utils.maintenance.node_operations import extract_nodes  # noqa: E402
finally:
    if _dotenv_disabled_before_import is None:
        os.environ.pop(_DOTENV_DISABLED_KEY, None)
    else:
        os.environ[_DOTENV_DISABLED_KEY] = _dotenv_disabled_before_import

if is_telemetry_enabled():  # pragma: no cover - guarded by the environment set above
    raise RuntimeError("Graphiti telemetry must be disabled")

GRAPHITI_VERSION = "0.30.2"

__all__ = [
    "GRAPHITI_VERSION",
    "CrossEncoderClient",
    "Edge",
    "EmbedderClient",
    "EntityNode",
    "EpisodeType",
    "EpisodicNode",
    "ExtractedEdges",
    "GraphDriver",
    "GraphDriverSession",
    "GraphProvider",
    "Graphiti",
    "GraphitiClients",
    "LLMClient",
    "LLMConfig",
    "ModelSize",
    "NoOpTracer",
    "NodeNotFoundError",
    "SearchFilters",
    "Transaction",
    "edge_fulltext_search",
    "edge_similarity_search",
    "extract_edges",
    "extract_nodes",
    "get_range_indices",
    "is_telemetry_enabled",
]
