"""Structural guarantees of the projection slice: no create_task dispatch, no subprocess, and the registered lexical statements as the only retrieval path."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.services import knowledge as evidence_package
from app.services.knowledge.evidence_index.operations import (
    SEARCH_EVIDENCE_LEXICAL,
    SEARCH_EVIDENCE_LEXICAL_PAIR,
)


def test_the_slice_never_dispatches_with_create_task_and_spawns_no_subprocess():
    """Only the managed workers own a task, and no parser is spawned."""
    package = Path(inspect.getfile(evidence_package)).parent
    sources = sorted(package.rglob("*.py"))
    assert sources
    forbidden_calls = {"create_task", "run", "Popen", "check_output", "call", "system", "spawn"}
    # ``_client`` / ``client`` are the Evidence index client held by the query store.
    allowed_run_receivers = {"runtime_client", "_client", "client"}
    # The projection worker, the Source Sync scheduler and the structured build runner
    # (owned by the projection worker) each own exactly one managed task.
    managed_workers = {"projection/worker.py", "sources/sync/scheduler.py", "structured/build_runner.py"}
    managed_worker_task_calls = 0
    # The local query embedder's warm-up: the application lifespan starts it once in the
    # background on the running loop so the first search does not pay the model load; it dispatches nothing.
    lifespan_warmups = {"embedding/warmup.py"}
    lifespan_warmup_tasks = 0
    # The evaluation CLIs (retrieval; change typing; the Library evaluation's ``capture``) are
    # operator entry points: each ``__main__`` runs one event loop.
    operator_entries = {"eval/run.py", "eval/change_typing.py", "eval/library_run.py"}
    operator_entry_loops = 0
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        # ``os`` itself is allowed: the runtime reads os.environ. Process spawning
        # is excluded by the modules below plus the call check further down.
        assert not modules & {"subprocess", "multiprocessing", "shlex", "pty", "asyncio.subprocess"}, path.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in forbidden_calls:
                continue
            receiver = node.func.value
            if (
                path.relative_to(package).as_posix() in managed_workers
                and node.func.attr == "create_task"
                and isinstance(receiver, ast.Name)
                and receiver.id == "asyncio"
            ):
                managed_worker_task_calls += 1
                continue
            if (
                path.relative_to(package).as_posix() in operator_entries
                and node.func.attr == "run"
                and isinstance(receiver, ast.Name)
                and receiver.id == "asyncio"
            ):
                operator_entry_loops += 1
                continue
            if (
                path.relative_to(package).as_posix() in lifespan_warmups
                and node.func.attr == "create_task"
                and isinstance(receiver, ast.Call)
                and getattr(receiver.func, "attr", None) == "get_running_loop"
            ):
                lifespan_warmup_tasks += 1
                continue
            # ``client.run(...)`` is the closed Evidence index registry call, not a process.
            receiver_name = receiver.attr if isinstance(receiver, ast.Attribute) else getattr(receiver, "id", None)
            assert node.func.attr == "run" and receiver_name in allowed_run_receivers, (
                f"{path.name} calls {node.func.attr}"
            )
    assert managed_worker_task_calls == len(managed_workers)
    assert operator_entry_loops == len(operator_entries)
    assert lifespan_warmup_tasks == len(lifespan_warmups)


def test_the_registered_lexical_statements_are_the_only_retrieval_path():
    from app.services.knowledge.retrieval import index_query_store, lexical_recall

    plan_source = inspect.getsource(lexical_recall)
    adapter_source = inspect.getsource(index_query_store)
    # The plan names the registry constants; neither module holds statement text.
    assert "SEARCH_EVIDENCE_LEXICAL" in plan_source and "SEARCH_EVIDENCE_LEXICAL_PAIR" in plan_source
    assert SEARCH_EVIDENCE_LEXICAL == "search_evidence_lexical_v2"
    assert SEARCH_EVIDENCE_LEXICAL_PAIR == "search_evidence_lexical_pair_v2"
    for source in (plan_source, adapter_source):
        assert "SELECT " not in source
        # No fallback import anywhere on the retrieval path.
        for legacy in ("knowledge_chunking", "knowledge_graph", "knowledge_embedding", "legacy_query_store"):
            assert legacy not in source
