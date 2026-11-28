"""C's new shipped graph earns exact-pushed-commit CI gates; lint is the pipeline's, never a server gate."""
from __future__ import annotations

import copy

import pytest

from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.seeding import phased_seeds
from app.services.workflow_runs.watch import deliver_event, poll_watching_runs
from app.services.workflow_runs.watch_events import WatchEvent
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_platform_actions import _run

pytestmark = pytest.mark.usefixtures("scripted_pool")


def c_definition():
    return copy.deepcopy(next(s['definition'] for s in phased_seeds() if s['key'] == 'bug-fix-reproduction'))


def test_c_ships_ci_before_merge_and_no_server_lint_gate():
    definition = c_definition()
    assert validate_flow_definition(definition)['valid']
    nodes = {n['id']: n for n in definition['nodes']}
    assert 'lint_passed' not in str(definition)
    assert nodes['ci']['config'] == {'conditions': ['ci.succeeded', 'ci.failed'], 'advance': 'auto'}
    assert not any(e['source_node_id'] == 'in_review' and e['target_node_id'] == 'merged'
                   for e in definition['edges'])
    loop = next(e for e in definition['edges'] if e['id'] == 'loop-ci')
    assert (loop['target_node_id'], loop['max_iterations']) == ('fix', 2)


@pytest.mark.asyncio
@pytest.mark.parametrize('condition,target', [('ci.succeeded', 'merged'), ('ci.failed', 'fix')])
async def test_c_native_ci_waits_for_the_pushed_sha_then_uses_its_real_edges(db, monkeypatch, condition, target):
    definition = c_definition()
    definition['edges'] = [e for e in definition['edges'] if e['source_node_id'] != 'start']
    definition['edges'].append({'id': 'test-start', 'source_node_id': 'start', 'target_node_id': 'ci'})
    run = await _run(db, definition, repository='bitbucket:acceptance/test')
    run.branch = 'bugfix/acceptance'
    run.context = {**run.context, 'head_sha': 'a' * 40}
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.hitl import enter_waiting_node
    graph = await graph_for_run(db, run)
    await enter_waiting_node(db, run, graph.nodes['ci'], actor_id=run.requested_by)
    await db.commit()
    assert (run.status, run.current_node_id) == ('waiting', 'ci')
    assert await deliver_event(db, WatchEvent(condition, 'bitbucket', 'acceptance/test',
                                            branch=run.branch, sha='b' * 40), source='test') == []
    await db.refresh(run)
    assert run.current_node_id == 'ci'
    # One Bitbucket success notification is insufficient; aggregate polling owns green.
    if condition == 'ci.succeeded':
        assert await deliver_event(db, WatchEvent(condition, 'bitbucket', 'acceptance/test',
                                                 branch=run.branch, sha='a' * 40), source='test') == []
    from app.services.workflow_runs.platform import ci
    from app.services.workflow_runs.platform.dispatch import read_outcome
    states = ['INPROGRESS', 'SUCCESSFUL' if condition == 'ci.succeeded' else 'FAILED']

    async def status_tool(db, current, tool, arguments, *, capability_class):
        assert tool == 'get_bitbucket_build_statuses'
        assert arguments['commit'] == 'a' * 40 and capability_class == 'read_only'
        return read_outcome({'statuses': [{'state': states.pop(0), 'url': 'https://ci.test/build'}]})

    monkeypatch.setattr(ci, 'dispatch_tool', status_tool)
    assert await poll_watching_runs(db) == 0
    await db.refresh(run)
    assert (run.status, run.current_node_id) == ('waiting', 'ci')
    assert await poll_watching_runs(db) == 1
    await db.refresh(run)
    assert run.current_node_id == target and run.outcome is None
    if condition == 'ci.failed':
        assert run.loop_counters['loop-ci']['used'] == 1


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
