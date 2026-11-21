import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import TestRenderer from 'react-test-renderer';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, JsxEmit } from 'typescript';
const loader = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Try the shared TS resolver. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith('.tsx')) return { format: 'module', shortCircuit: true, source: transpileModule(readFileSync(new URL(url), 'utf8'), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { WorkflowDecisionButton } = await import('../../src/chat/inbox/WorkflowDecisionButton.tsx');
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const confirm = { key: 'confirmed', label: 'Confirm this publication' };
const waiting = (hash = 'sha256:approved') => ({
  id: 'run/one', title: 'Publication decision', status: 'waiting',
  waiting: { kind: 'awaiting_confirmation', subject: 'publication', question: 'Publish this exact page?',
    payload_hash: hash, payload: { title: 'Approved documentation', body: '<p>Approved body</p>' } },
  actions: [confirm], runtime_target: { kind: 'device', device_id: 'owner-device' }, owner_session_id: 'owner-private',
});
const response = run => ({ ok: true, json: async () => ({ run }) });
const refused = () => ({ ok: false, status: 403, json: async () => ({ detail: 'private refusal details' }) });
const button = (view, label) => view.root.findAllByType('button').find(node => node.children.join('') === label);
async function scenario(handler, exercise) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return handler(path, init, calls.length); };
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(WorkflowDecisionButton, { runId: 'run/one' })); });
    await exercise(view, calls);
  } finally { act(() => view?.unmount()); globalThis.fetch = original; }
}

test('uses normal viewer authentication, offered actions, current hash and no owner session', async () => {
  await scenario((path, init) => response(init.method === 'POST' ? { ...waiting(), waiting: null, actions: [] } : waiting()), async (view, calls) => {
    assert.equal(calls.length, 0);
    await act(async () => { button(view, 'Open decision').props.onClick(); });
    const text = JSON.stringify(view.toJSON());
    assert.match(text, /Publish this exact page\?/);
    assert.match(text, /Approved body/);
    assert.match(text, /sha256:approved/);
    assert.equal(button(view, 'Abort'), undefined);
    await act(async () => { button(view, confirm.label).props.onClick(); });
    assert.equal(calls[0].path, '/api/v1/workflow-runs/run%2Fone');
    assert.equal(calls[1].path, '/api/v1/workflow-runs/run%2Fone/actions');
    assert.deepEqual(JSON.parse(calls[1].init.body), { action: 'confirmed', payload_hash: 'sha256:approved' });
    assert.ok(calls.every(call => call.init.credentials === 'same-origin'));
    assert.ok(calls.every(call => !/sessions|execution-target|by-session/.test(call.path)));
    assert.equal(button(view, confirm.label), undefined);
  });
});

test('refusal reloads current card without retry; a deliberate next action uses its new hash', async () => {
  await scenario((path, init, n) => n === 2 ? refused() : response(waiting(n >= 3 ? 'sha256:new' : 'sha256:approved')), async (view, calls) => {
    await act(async () => { button(view, 'Open decision').props.onClick(); });
    await act(async () => { button(view, confirm.label).props.onClick(); });
    assert.equal(calls.length, 3);
    assert.equal(calls.filter(call => call.init.method === 'POST').length, 1);
    assert.match(JSON.stringify(view.toJSON()), /sha256:new/);
    await act(async () => { button(view, confirm.label).props.onClick(); });
    assert.equal(JSON.parse(calls[3].init.body).payload_hash, 'sha256:new');
  });
});

test('role revocation closes old payload and actions when refreshed GET is also forbidden', async () => {
  await scenario((path, init, n) => n === 1 ? response(waiting()) : refused(), async (view, calls) => {
    await act(async () => { button(view, 'Open decision').props.onClick(); });
    await act(async () => { button(view, confirm.label).props.onClick(); });
    assert.equal(calls.length, 3);
    assert.equal(button(view, confirm.label), undefined);
    const text = JSON.stringify(view.toJSON());
    assert.doesNotMatch(text, /Approved body|sha256:approved|private refusal details/);
    assert.match(text, /no longer have access/);
  });
});

test('reply and reason post their offered input names; required empty text stays disabled', async () => {
  for (const name of ['reply', 'reason']) {
    const action = { key: name === 'reply' ? 'reply' : 'abort', label: `Send ${name}`,
      input: { name, kind: 'text', label: name, default: '', required: true } };
    await scenario(() => response({ ...waiting(), actions: [action] }), async (view, calls) => {
      await act(async () => { button(view, 'Open decision').props.onClick(); });
      assert.equal(button(view, action.label).props.disabled, true);
      act(() => { view.root.findByType('input').props.onChange({ target: { value: '  Actual viewer reply  ' } }); });
      await act(async () => { button(view, action.label).props.onClick(); });
      assert.deepEqual(JSON.parse(calls[1].init.body), { action: action.key, [name]: 'Actual viewer reply', payload_hash: 'sha256:approved' });
    });
  }
});

test('empty server subset and unsupported inputs do not invent action buttons', async () => {
  for (const actions of [[], [{ key: 'invented', label: 'Unsupported', input: { kind: 'script', name: 'code' } }]]) {
    await scenario(() => response({ ...waiting(), actions }), async (view) => {
      await act(async () => { button(view, 'Open decision').props.onClick(); });
      assert.deepEqual(view.root.findAllByType('button').map(node => node.children.join('')), ['Open decision', 'Close decision']);
    });
  }
});

test('new Inbox run identity discards the old card without loading an owner session', async () => {
  await scenario(() => response(waiting()), async (view, calls) => {
    await act(async () => { button(view, 'Open decision').props.onClick(); });
    act(() => { view.update(createElement(WorkflowDecisionButton, { runId: 'run/two' })); });
    assert.doesNotMatch(JSON.stringify(view.toJSON()), /Approved body|sha256:approved/);
    assert.equal(calls.length, 1);
  });
});

test('typed number and runtime choice inputs use the server schema without local target rewriting', async () => {
  const cases = [
    { action: { key: 'retry', label: 'Retry once', input: { kind: 'number', name: 'iterations', label: 'Extra iterations', min: 1, max: 8, default: 1 } }, type: 'input', value: '2', expected: { iterations: 2 } },
    { action: { key: 'change_runtime', label: 'Change runtime', input: { kind: 'runtime_target', name: 'runtime_target', label: 'Run on', default: 'server', options: [{ key: 'server', label: 'Server', target: { kind: 'server' } }, { key: 'device', label: 'My device', target: { kind: 'device', device_id: 'mine', folder: '/safe' } }] } }, type: 'select', value: 'device', expected: { runtime_target: { kind: 'device', device_id: 'mine', folder: '/safe' } } },
  ];
  for (const { action, type, value, expected } of cases) {
    await scenario(() => response({ ...waiting(), actions: [action] }), async (view, calls) => {
      await act(async () => { button(view, 'Open decision').props.onClick(); });
      act(() => { view.root.findByType(type).props.onChange({ target: { value } }); });
      await act(async () => { button(view, action.label).props.onClick(); });
      assert.deepEqual(JSON.parse(calls[1].init.body), { action: action.key, ...expected, payload_hash: 'sha256:approved' });
      assert.equal(calls.length, 2);
    });
  }
});

test('an in-flight decision cannot be submitted twice', async () => {
  let release;
  await scenario(async (path, init) => {
    if (init.method === 'POST') await new Promise(resolve => { release = resolve; });
    return response(waiting());
  }, async (view, calls) => {
    await act(async () => { button(view, 'Open decision').props.onClick(); });
    const offered = button(view, confirm.label);
    act(() => { offered.props.onClick(); offered.props.onClick(); });
    assert.equal(calls.length, 2);
    assert.equal(button(view, confirm.label).props.disabled, true);
    await act(async () => { release(); });
  });
});
