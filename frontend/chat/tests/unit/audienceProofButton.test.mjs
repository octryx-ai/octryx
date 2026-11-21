import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import TestRenderer from 'react-test-renderer';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, JsxEmit } from 'typescript';
const loader = registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.tsx')) return { format: 'module', shortCircuit: true, source: transpileModule(readFileSync(new URL(url), 'utf8'), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { AudienceProofButton } = await import('../../src/chat/inbox/AudienceProofButton.tsx');
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

test('the assigned person uses normal authentication and duplicate clicks stay disabled', async () => {
  const original = globalThis.fetch;
  const calls = [];
  let release;
  globalThis.fetch = async (...args) => { calls.push(args); await new Promise(resolve => { release = resolve; }); return { ok: true, json: async () => ({ proof: { state: 'recorded' } }) }; };
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(AudienceProofButton, { challengeId: 'opaque/challenge' })); });
    act(() => { view.root.findByType('button').props.onClick(); });
    assert.equal(view.root.findByType('button').props.disabled, true);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], '/api/v1/workflow-runs/audience-receipts/opaque%2Fchallenge/record');
    assert.equal(calls[0][1].method, 'POST');
    assert.equal(calls[0][1].credentials, 'same-origin');
    assert.equal(calls[0][1].body, undefined);
    await act(async () => { release(); });
    assert.equal(view.root.findByType('button').children.join(''), 'Recorded');
    assert.equal(view.root.findByType('button').props.disabled, true);
  } finally { view?.unmount(); globalThis.fetch = original; }
});

test('a refusal shows no target data and leaves a deliberate retry', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 403, json: async () => ({ detail: 'internal target data' }) });
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(AudienceProofButton, { challengeId: 'opaque' })); });
    await act(async () => { view.root.findByType('button').props.onClick(); });
    assert.equal(view.root.findByType('button').props.disabled, false);
    const text = JSON.stringify(view.toJSON());
    assert.match(text, /The check could not be recorded/);
    assert.doesNotMatch(text, /internal target data/);
  } finally { view?.unmount(); globalThis.fetch = original; }
});
