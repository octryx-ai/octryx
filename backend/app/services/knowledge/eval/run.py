"""Run a golden set against an evaluation Workspace and compare configurations.

    python -m app.services.knowledge.eval.run --workspace <id> --golden spring_boot \\
        --spaces local_mlminilm_384_v1,bedrock_titan2_1024_v1 [--reranker bedrock_cohere_rerank35_v1]

Runs inside the API image, which holds the stores' configuration. For each embedding space the
Workspace is embedded directly (``embed_corpus``), then every query runs lexical once and vector,
hybrid, and optionally hybrid with rerank per space, through the product retrieval functions.
Prints one JSON document: per configuration the metrics, per query the rank of the first correct hit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from sqlalchemy import select

from ....models import User
from ...data_access import as_viewer
from ..access.authorization import authorize_workspace
from ..embedding.selection import SPACE_ENV
from ..ledger.errors import EvidenceLedgerError
from ..rerank.selection import RERANKER_ENV
from ..retrieval.evidence import LEXICAL_MODES, VECTOR_MODES, retrieve_workspace_evidence
from ..retrieval.hybrid import hybrid_workspace_evidence
from ..runtime import build_evidence_runtime
from .embed_corpus import embed_workspace
from .golden import GoldenSet, load_golden_set
from .metrics import ConfigurationReport, QueryOutcome, first_correct_rank

RESULT_LIMIT = 10


async def _hits(db, runtime, authorized, query, mode: str) -> list[tuple[str, str]]:
    scope = {"products": list(query.products) or None, "version": query.version}
    if mode == "hybrid":
        result = await hybrid_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text=query.question, limit=RESULT_LIMIT, **scope
        )
        return [(hit.evidence.source_title, hit.evidence.text) for hit in result.evidence]
    modes = LEXICAL_MODES if mode == "lexical" else VECTOR_MODES
    result = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text=query.question, limit=RESULT_LIMIT, modes=modes, **scope
    )
    return [(item.source_title, item.text) for item in result.evidence]


async def _evaluate(db, runtime, authorized, golden: GoldenSet, name: str, mode: str) -> ConfigurationReport:
    report = ConfigurationReport(name=name)
    for query in golden.queries:
        started = time.perf_counter()
        try:
            hits = await _hits(db, runtime, authorized, query, mode)
            state = "ok"
        except EvidenceLedgerError as error:
            hits, state = [], error.state.value
        latency = (time.perf_counter() - started) * 1000
        rank = first_correct_rank(hits, source_title=golden.sources[query.source].title, passage=query.passage)
        report.outcomes.append(QueryOutcome(query.id, query.lang, rank, len(hits), latency, state))
    return report


async def main(args: argparse.Namespace) -> dict:
    import app.db as database

    golden = load_golden_set(args.golden)
    reports: list[ConfigurationReport] = []
    async with database.async_session_factory() as db:
        admin = (await db.execute(select(User).where(User.username == args.user))).scalar_one()
        with as_viewer(admin.id):
            authorized = await authorize_workspace(db, current_user=admin, workspace_id=args.workspace)
            base = build_evidence_runtime({**os.environ, SPACE_ENV: "", RERANKER_ENV: ""})
            reports.append(await _evaluate(db, base, authorized, golden, "lexical", "lexical"))
            for space in [item for item in args.spaces.split(",") if item]:
                runtime = build_evidence_runtime({**os.environ, SPACE_ENV: space, RERANKER_ENV: ""})
                embedded = await embed_workspace(db, runtime=runtime, authorized=authorized)
                reports.append(await _evaluate(db, runtime, authorized, golden, f"vector:{space}", "vector"))
                reports.append(await _evaluate(db, runtime, authorized, golden, f"hybrid:{space}", "hybrid"))
                if args.reranker:
                    ranked = build_evidence_runtime({**os.environ, SPACE_ENV: space, RERANKER_ENV: args.reranker})
                    name = f"hybrid+{args.reranker}:{space}"
                    reports.append(await _evaluate(db, ranked, authorized, golden, name, "hybrid"))
                print(json.dumps({"embedded": space, "spans": embedded}), flush=True)
    return {
        "golden": args.golden,
        "summaries": [report.summary() for report in reports],
        "ranks": {report.name: {o.query_id: o.first_correct_rank for o in report.outcomes} for report in reports},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--golden", default="spring_boot")
    parser.add_argument("--spaces", default="local_mlminilm_384_v1")
    parser.add_argument("--reranker", default="")
    parser.add_argument("--user", default="admin")
    return parser


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(_parser().parse_args())), indent=2))
