import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import TestRenderer from 'react-test-renderer';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, JsxEmit } from 'typescript';
const loader = registerHooks({ load(url, context, nextLoad) {
  if (url.endsWith('.tsx')) return { format: 'module', shortCircuit: true, source: transpileModule(readFileSync(new URL(url), 'utf8'), {
    compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
  }).outputText };
  return nextLoad(url, context);
} });
const { WorkflowHandoffButton } = await import('../../src/chat/inbox/WorkflowHandoffButton.tsx');
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const hash = `sha256:${'a'.repeat(64)}`;
const offer = (changes = {}) => ({ id: 'offer/one', state: 'offered', payload_hash: hash, round: 1, state_version: 7,
  acceptance: 'Inspect the approved task.', artefacts: { definition_of_ready: { version: 3, record: { summary: 'Approved task' } } },
  scope: { workspace_id: 'approved-space' }, expires_at: '2026-10-15T00:00:00Z', ...changes });
const ok = body => ({ ok: true, json: async () => body });
const deny = status => ({ ok: false, status, json: async () => ({ detail: 'private error with credential' }) });
const button = (view, label) => view.root.findAllByType('button').find(node => node.children.join('') === label);
const accept = 'Accept and initialize on Server', decline = 'Decline this round';
const accepted = state => ({ handoff: { id: 'offer/one', state: 'accepted' }, continuation: { state, receiver_session_id: 'receiver/own' } });
async function scenario(handler, exercise) {
  const original = globalThis.fetch, calls = []; let view;
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return handler(path, init, calls.length); };
  try {
    act(() => { view = TestRenderer.create(createElement(WorkflowHandoffButton, { handoffId: 'offer/one' })); });
    await exercise(view, calls);
  } finally { act(() => view?.unmount()); globalThis.fetch = original; }
}
const open = async view => { await act(async () => { button(view, 'Open handoff').props.onClick(); }); };
const selectServer = view => { act(() => { view.root.findByType('select').props.onChange({ target: { value: 'server' } }); }); };

test('actual viewer preview requires explicit Server selection and sends current hash round and version', async () => {
  await scenario((path, init) => ok(init.method === 'POST' ? accepted('started') : { handoff: offer() }), async (view, calls) => {
    assert.equal(calls.length, 0); await open(view);
    assert.equal(button(view, accept).props.disabled, true);
    assert.equal(view.root.findByType('select').props.value, '');
    assert.match(JSON.stringify(view.toJSON()), /Approved task|Inspect the approved task/);
    assert.match(JSON.stringify(view.toJSON()), /Device and Terminal selection are not yet available/);
    assert.equal(view.root.findAllByType('a').length, 0);
    selectServer(view); await act(async () => { button(view, accept).props.onClick(); });
    assert.deepEqual(JSON.parse(calls[1].init.body), { action: 'accept', payload_hash: hash, round: 1,
      expected_state_version: 7, runtime_target: { kind: 'server' } });
    assert.equal(calls[0].path, '/api/v1/workflow-handoffs/offer%2Fone');
    assert.equal(calls[1].path, '/api/v1/workflow-handoffs/offer%2Fone/actions');
    assert.ok(calls.every(call => call.init.credentials === 'same-origin'));
    assert.ok(calls.every(call => !/sessions|execution-target/.test(call.path)));
    assert.equal(view.root.findByType('a').props.href, '/chat?session_id=receiver%2Fown');
    assert.match(JSON.stringify(view.toJSON()), /was initialized/);
    assert.equal(button(view, accept), undefined);
  });
});

test('personal decline requires reason, sends no runtime or different actor, and opens no child', async () => {
  await scenario((path, init) => ok(init.method === 'POST'
    ? { handoff: { id: 'offer/one', state: 'offered', personal_response: 'declined' }, continuation: null }
    : { handoff: offer() }), async (view, calls) => {
    await open(view); assert.equal(button(view, decline).props.disabled, true);
    act(() => { view.root.findByType('input').props.onChange({ target: { value: '  Not available today  ' } }); });
    await act(async () => { button(view, decline).props.onClick(); });
    assert.deepEqual(JSON.parse(calls[1].init.body), { action: 'decline', payload_hash: hash, round: 1,
      expected_state_version: 7, reason: 'Not available today' });
    assert.match(JSON.stringify(view.toJSON()), /You declined this round/);
    assert.equal(view.root.findAllByType('a').length, 0);
  });
});

test('held acceptance is honest and exposes only receiver-owned child navigation', async () => {
  await scenario((path, init) => ok(init.method === 'POST' ? accepted('held') : { handoff: offer() }), async (view) => {
    await open(view); selectServer(view); await act(async () => { button(view, accept).props.onClick(); });
    assert.match(JSON.stringify(view.toJSON()), /initialization is held/);
    assert.doesNotMatch(JSON.stringify(view.toJSON()), /workflow completed|was initialized/);
    assert.equal(view.root.findByType('a').props.href, '/chat?session_id=receiver%2Fown');
  });
});

test('409 reloads current hash round version and requires another deliberate runtime choice', async () => {
  const fresh = `sha256:${'b'.repeat(64)}`;
  await scenario((path, init, n) => n === 2 ? deny(409) : ok({ handoff: offer(n >= 3
    ? { payload_hash: fresh, round: 2, state_version: 8 } : {}) }), async (view, calls) => {
    await open(view); selectServer(view); await act(async () => { button(view, accept).props.onClick(); });
    assert.equal(calls.length, 3); assert.equal(button(view, accept).props.disabled, true);
    assert.match(JSON.stringify(view.toJSON()), new RegExp(fresh));
    selectServer(view); await act(async () => { button(view, accept).props.onClick(); });
    const sent = JSON.parse(calls[3].init.body);
    assert.equal(sent.payload_hash, fresh); assert.equal(sent.round, 2); assert.equal(sent.expected_state_version, 8);
  });
});

test('revoked membership clears the approved card and actions without showing internal errors', async () => {
  await scenario((path, init, n) => n === 1 ? ok({ handoff: offer() }) : deny(403), async (view, calls) => {
    await open(view); selectServer(view); await act(async () => { button(view, accept).props.onClick(); });
    assert.equal(calls.length, 3); assert.equal(button(view, accept), undefined);
    assert.doesNotMatch(JSON.stringify(view.toJSON()), /Approved task|approved-space|private error|credential/);
    assert.match(JSON.stringify(view.toJSON()), /no longer have access/);
  });
});

test('stopped and malformed offers do not display arbitrary actions or child links', async () => {
  for (const current of [offer({ state: 'stopped' }), offer({ payload_hash: 'unproved' })]) {
    await scenario(() => ok({ handoff: current }), async (view) => {
      await open(view); assert.equal(button(view, accept), undefined); assert.equal(button(view, decline), undefined);
      assert.equal(view.root.findAllByType('a').length, 0);
    });
  }
});

test('in-flight duplicate acceptance produces one POST', async () => {
  let release;
  await scenario(async (path, init) => {
    if (init.method === 'POST') { await new Promise(resolve => { release = resolve; }); return ok(accepted('held')); }
    return ok({ handoff: offer() });
  }, async (view, calls) => {
    await open(view); selectServer(view); const chosen = button(view, accept);
    act(() => { chosen.props.onClick(); chosen.props.onClick(); });
    assert.equal(calls.length, 2); assert.equal(button(view, accept).props.disabled, true);
    await act(async () => { release(); });
  });
});
