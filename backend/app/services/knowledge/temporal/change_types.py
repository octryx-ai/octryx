"""Typed change records: how a versioned document's facts are classified (typing v2).

Graphiti accepts custom fact (edge) types: a name and a description it offers the extraction model.
A revision that carries a subject version (a release note, a migration guide, a configuration
changelog) is extracted with the change-record types and an explicit instruction naming the
product and version. Both are data: the ``change-records`` profile in
``profiles/change_records.json`` (loaded and validated by ``extraction_profiles.py``). This module
names the profile the change-record reads are built on and exposes its closed types, so each fact
says *what kind of change* it is. The impact join (``code/impact.py``) acts on the types that
require a change in code (``action_required``), and never on ``INTRODUCED``, which describes a
new capability rather than a required change.

Each type's description is a definition with one positive and one negative example, so ``REQUIRES`` does not absorb
every fact that fits no other type (descriptions of behaviour, new capabilities, limitations of other products). Two
rules carry that:

- A statement that only describes behaviour or a feature, without a change in the documented
  version, is **not** a change record: it keeps a descriptive relation of the model's own.
- A dependency upgrade to a named version is ``REQUIRES``, always. Whether an upgrade is "major"
  cannot be read reliably from the text, so the rule is the same for every upgrade and precision
  stays measurable (``eval/change_typing.py``).

A limitation or incompatibility of another product ("Spock does not yet support Groovy 5") is not
a change of this product and has no type of its own: the page ranking and the impact join are
built on this closed set, so a new type would be its own slice.

The extraction answer also carries a typed self-check per fact (``change_self_check.py``). The type
models themselves have no fields on purpose: a field would make Graphiti spend one more model call
per fact on attribute extraction.

The profile id is recorded with every episode (``knowledge_graph_episodes.extraction_profile``).
Changing these types, their descriptions or the instruction means a new profile version; episodes
of a profile that is no longer current are purged from their product's graph before anything is
extracted there again (``profile_migration.py``), so a graph never mixes classifications.
"""

from __future__ import annotations

from .extraction_profiles import extraction_profiles

# The profile the change-record reads are built on (``knowledge_changes``, the impact join, the page
# ranking): its closed types are what those reads filter by.
CHANGE_RECORDS_PROFILE = "change-records-v2"
_CHANGE_RECORDS = extraction_profiles()[CHANGE_RECORDS_PROFILE]
# The profiles extraction writes today; an episode under any other profile is stale.
CURRENT_PROFILES = frozenset(extraction_profiles())
# The relation a fact keeps when its own self-check says it states no change (never a change type).
NOT_A_CHANGE_RELATION = "DESCRIBES"

CHANGE_EDGE_TYPES = _CHANGE_RECORDS.edge_types or {}
# The kinds that can require a change in an existing codebase.
ACTION_REQUIRED_TYPES = _CHANGE_RECORDS.action_required_types


def change_instructions(product: str, version: str) -> str:
    return _CHANGE_RECORDS.instructions(product, version) or ""


__all__ = [
    "ACTION_REQUIRED_TYPES",
    "CHANGE_EDGE_TYPES",
    "CHANGE_RECORDS_PROFILE",
    "CURRENT_PROFILES",
    "NOT_A_CHANGE_RELATION",
    "change_instructions",
]
