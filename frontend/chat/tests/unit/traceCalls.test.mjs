// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/traceCalls.test.mjs
//
// The model calls behind one answer in the trace view (seat and device answers had no trace). The server
// lists every call of the turn; the view shows one line per call, sums the turn in its heading and says honestly
// when no gateway call is linked to a device turn.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared hook resolves pure TS. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});

const { callFacts, callTotals, callsHeading, deviceNote, DEVICE_NO_CALLS_NOTE, DEVICE_CALLS_NOTE } =
  await import("../../src/chat/traceCallsModel.ts");
const { TraceCallsSection } = await import("../../src/chat/traceCallsSection.tsx");

const call = (id, input, extra = {}) => ({
  id, provider: "anthropic_seat", model: "claude-sonnet-5-5", createdAt: "2026-11-20T13:02:31",
  tokens: { input, output: 7, cacheRead: 0, cacheCreation: 0 }, durationMs: 1500, stopReason: "tool_use", ...extra,
});
const trace = (extra = {}) => ({
  id: "t3", provider: "anthropic_seat", model: "claude-sonnet-5-5", inputMessages: [], contextSnapshot: {},
  toolTrace: [], rawOutput: {}, usage: {}, createdAt: null, ...extra,
});

test("a call's line names its tokens, cache, time and how it ended", () => {
  assert.equal(callFacts(call("a", 1200, { tokens: { input: 1200, output: 7, cacheRead: 3, cacheCreation: 0 } })),
    "1'200 in · 7 out · 3 cached · 1.5 s · tool_use");
  assert.equal(callFacts(call("b", 5, { durationMs: null, stopReason: "" })), "5 in · 7 out");
});

test("the heading sums the whole turn", () => {
  const calls = [call("a", 100), call("b", 200), call("c", 300, { stopReason: "end_turn" })];
  assert.deepEqual(callTotals(calls), { input: 600, output: 21, cacheRead: 0, cacheCreation: 0 });
  assert.equal(callsHeading(calls), "3 model calls · 600 in · 21 out");
  assert.equal(callsHeading([call("a", 1)]), "1 model call · 1 in · 7 out");
});

test("a device turn names its linked calls, or says honestly that none are linked", () => {
  assert.equal(deviceNote(trace({ provider: "device", promptOnDevice: true })), DEVICE_NO_CALLS_NOTE);
  assert.equal(deviceNote(trace({ provider: "device", calls: [call("a", 1)] })), DEVICE_CALLS_NOTE);
  assert.equal(deviceNote(trace({ calls: [call("a", 1)] })), null);
});

test("the section lists every call and hides itself for a trace without calls", () => {
  const html = renderToStaticMarkup(createElement(TraceCallsSection, {
    trace: trace({ calls: [call("a", 100), call("t3", 300, { stopReason: "end_turn" })] }),
    loadTrace: async () => null,
  }));
  assert.equal(html.match(/data-testid="trace-call"/g).length, 2);
  assert.match(html, /2 model calls · 400 in · 14 out/);
  assert.match(html, /aria-label="Show call 1"/);
  assert.equal(renderToStaticMarkup(createElement(TraceCallsSection, { trace: trace() })), "");
});

test("a device turn without platform calls shows only the note", () => {
  const html = renderToStaticMarkup(createElement(TraceCallsSection, {
    trace: trace({ provider: "device", promptOnDevice: true, calls: [] }),
  }));
  assert.match(html, /No gateway calls are linked to this turn/);
  assert.doesNotMatch(html, /trace-call"/);
});
