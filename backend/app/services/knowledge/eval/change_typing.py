"""Measure change-record typing on a labeled golden set, with the real governed extraction (typing v2).

    python -m app.services.knowledge.eval.change_typing --workspace <id> \\
        [--golden change_typing_spring_boot] [--user admin] [--facts]

Opt-in, never a unit test: every sentence costs governed model calls. Runs inside the API image,
which holds the control-plane runtimes. Each golden sentence goes through Graphiti's own entity
and fact extraction (the functions ``add_episode`` runs) with the Workspace's admitted model, the
change-record types, the instruction and the typed self-check of the current profile
(``temporal/change_types.py``, ``temporal/change_self_check.py``). Nothing is written and nothing
is embedded: the graph driver and the embedder given to Graphiti refuse every call.

Scoring is per sentence. A sentence's prediction is the set of change types among the facts
extracted from it, after the guard. For each type T:

- precision = sentences labeled T whose facts include T / sentences whose facts include T;
- recall = sentences labeled T whose facts include T / sentences labeled T.

A ``NONE`` sentence with any change type is a false positive of that type. Prints one JSON
document: per-type precision and recall, the ``NONE`` false-change rate, facts the guard stripped
of a change type, and model usage. With ``--facts`` it also lists each extracted fact; the golden
sentences are public vendor documentation, never Workspace content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from ....models import User
from ..access.authorization import authorize_workspace
from ..temporal.change_types import CHANGE_EDGE_TYPES, CHANGE_RECORDS_PROFILE, change_instructions
from ..temporal.errors import GraphStoreError, GraphStoreState
from ..temporal.graphiti_adapters import RefusingCrossEncoder
from ..temporal.graphiti_boundary import (
    EmbedderClient,
    EpisodeType,
    EpisodicNode,
    GraphDriver,
    GraphitiClients,
    NoOpTracer,
    extract_edges,
    extract_nodes,
)
from ..temporal.graphiti_llm import governed_graph_llm
from .golden import GOLDEN_DIR

NONE = "NONE"
LABELS = frozenset(CHANGE_EDGE_TYPES) | {NONE}


@dataclass(frozen=True, slots=True)
class TypingSentence:
    id: str
    text: str
    expected: str


@dataclass(frozen=True, slots=True)
class TypingGolden:
    product: str
    version: str
    sentences: tuple[TypingSentence, ...]


def load_typing_golden(name: str) -> TypingGolden:
    """Load ``golden/<name>.json``; every label is a change type or ``NONE`` and ids are unique."""
    raw = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
    sentences = tuple(TypingSentence(item["id"], item["text"], item["expected"]) for item in raw["sentences"])
    if len({item.id for item in sentences}) != len(sentences):
        raise ValueError("duplicate golden sentence id")
    unknown = sorted({item.expected for item in sentences} - LABELS)
    if unknown:
        raise ValueError(f"golden labels outside the closed change types: {unknown}")
    return TypingGolden(product=raw["product"], version=raw["version"], sentences=sentences)


def score(golden: TypingGolden, predicted: dict[str, set[str]]) -> dict:
    """Per-type precision and recall over sentences, and the false-change rate of ``NONE`` sentences."""
    per_type = {}
    for kind in sorted(CHANGE_EDGE_TYPES):
        labeled = {item.id for item in golden.sentences if item.expected == kind}
        hit = {sentence_id for sentence_id, kinds in predicted.items() if kind in kinds}
        true_positive = len(labeled & hit)
        per_type[kind] = {
            "labeled": len(labeled),
            "predicted": len(hit),
            "precision": round(true_positive / len(hit), 3) if hit else None,
            "recall": round(true_positive / len(labeled), 3) if labeled else None,
            "false_positives": sorted(hit - labeled),
        }
    unchanged = [item.id for item in golden.sentences if item.expected == NONE]
    typed_anyway = sorted(sentence_id for sentence_id in unchanged if predicted.get(sentence_id))
    return {
        "per_type": per_type,
        "none_sentences": len(unchanged),
        "none_typed_as_change": typed_anyway,
        "exact_sentences": sum(
            1
            for item in golden.sentences
            if predicted.get(item.id, set()) == (set() if item.expected == NONE else {item.expected})
        ),
    }


class _NoGraph(GraphDriver):
    """Graphiti's driver slot for a run that must write nothing: every statement is refused."""

    def _refuse(self, *args, **kwargs):
        raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)

    execute_query = session = delete_all_indexes = _refuse

    async def build_indices_and_constraints(self, delete_existing: bool = False):
        self._refuse()

    async def close(self):
        return None


class _NoEmbedder(EmbedderClient):
    async def create(self, input_data):
        raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)


async def _typed_facts(clients: GraphitiClients, golden: TypingGolden, sentence: TypingSentence) -> list[dict]:
    """The facts Graphiti extracts from one sentence under the change-record profile, as add_episode would."""
    instructions = change_instructions(golden.product, golden.version)
    episode = EpisodicNode(
        name=sentence.id,
        group_id=golden.product,
        labels=[],
        source=EpisodeType.text,
        source_description=f"{golden.product} (version {golden.version})",
        content=sentence.text,
        created_at=datetime.now(UTC),
        valid_at=datetime.now(UTC),
    )
    nodes, _ = await extract_nodes(clients, episode, [], None, None, instructions)
    edges = await extract_edges(
        clients,
        episode,
        nodes,
        [],
        {("Entity", "Entity"): list(CHANGE_EDGE_TYPES)},
        golden.product,
        CHANGE_EDGE_TYPES,
        instructions,
    )
    return [{"relation": edge.name, "fact": edge.fact} for edge in edges]


async def main(args: argparse.Namespace) -> dict:
    import app.db as database

    golden = load_typing_golden(args.golden)
    predicted: dict[str, set[str]] = {}
    facts: dict[str, list[dict]] = {}
    failed: list[str] = []
    async with database.async_session_factory() as db:
        admin = (await db.execute(select(User).where(User.username == args.user))).scalar_one()
        authorized = await authorize_workspace(db, current_user=admin, workspace_id=args.workspace)
        llm = await governed_graph_llm(db, project_id=authorized.project_id, check_change_edges=True)
    clients = GraphitiClients(
        driver=_NoGraph(),
        llm_client=llm,
        embedder=_NoEmbedder(),
        cross_encoder=RefusingCrossEncoder(),
        tracer=NoOpTracer(),
    )
    for sentence in golden.sentences:
        try:
            extracted = await _typed_facts(clients, golden, sentence)
        except Exception as error:  # noqa: BLE001 - one failed sentence is reported by id and error class only
            failed.append(f"{sentence.id}:{type(error).__name__}")
            continue
        facts[sentence.id] = extracted
        predicted[sentence.id] = {item["relation"] for item in extracted if item["relation"] in CHANGE_EDGE_TYPES}
    report = {
        "golden": args.golden,
        "profile": CHANGE_RECORDS_PROFILE,
        "sentences": len(golden.sentences),
        "failed": failed,
        **score(golden, predicted),
        "relations": dict(Counter(item["relation"] for extracted in facts.values() for item in extracted)),
        "demoted_by_self_check": llm.usage.demoted,
        "usage": {
            "calls": llm.usage.calls,
            "input_tokens": llm.usage.input_tokens,
            "output_tokens": llm.usage.output_tokens,
            "unparseable": llm.usage.unparseable,
            "models": sorted(llm.usage.models),
        },
        "predicted": {key: sorted(value) for key, value in predicted.items()},
    }
    if args.facts:
        report["facts"] = facts
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--golden", default="change_typing_spring_boot")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--facts", action="store_true", help="also list every extracted fact")
    return parser


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(_parser().parse_args())), indent=2))
