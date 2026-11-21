"""The epic-delivery seed definition and the story run shared by the story session tests."""

from __future__ import annotations

import copy

from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import PHASE
from tests.workflow_run_octryx_continuation_support import DEFINITION


def _seed(key: str = "epic-delivery") -> dict:
    return next(item for item in seed_definitions() if item["key"] == key)


STORY = {
    "execution_kind": "phased",
    "nodes": [*DEFINITION["nodes"][:2],
              {"id": "work", "type": "phase", "label": "Implement", "config": {**copy.deepcopy(PHASE),
                                                                               "subagents": True}},
              {"id": "pipeline", "type": "platform_action", "label": "CI", "config": {"action": "pipeline.run"}},
              *DEFINITION["nodes"][3:]],
    "edges": [*DEFINITION["edges"][:4],
              {"id": "e4", "source_node_id": "work", "target_node_id": "pipeline"},
              {"id": "e5", "source_node_id": "pipeline", "target_node_id": "done", "when": "succeeded"},
              {"id": "e6", "source_node_id": "pipeline", "target_node_id": "work", "when": "failed", "kind": "loop",
               "max_iterations": 3}],
}
