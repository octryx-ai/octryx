// W3 follow-up (UX review): the Work area shows one quiet line when the active Workspace has problems, and "Show"
// lists them in the side panel. None, 404 or an error: no line.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { workProblemsLine } from "../../src/chat/work/workProblemsModel.ts";
import { readProblems } from "../../src/admin/components/problems/problemsModel.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

const problem = (key, severity, kind = "intake") => ({ key, kind, severity, title: `Problem ${key}`, since: "2026-11-06T08:00:00+00:00",
  last_seen: null, count: 2, workspace: { id: "ws_1", name: "Test" }, object: null, fix: null });
const payload = (...problems) => ({ problems, counts: { problem: 0, attention: 0, by_kind: {} } });

test("the line counts the Workspace's Work problems and takes the problem tone when any is a problem", () => {
  assert.equal(workProblemsLine(null), null);
  assert.equal(workProblemsLine(readProblems(payload())), null, "no line without problems");
  assert.deepEqual(workProblemsLine(readProblems(payload(problem("a", "attention")))), { text: "1 needs attention in Work", tone: "attention", target: "work" });
  assert.deepEqual(workProblemsLine(readProblems(payload(problem("a", "attention"), problem("b", "attention", "run")))),
    { text: "2 need attention in Work", tone: "attention", target: "work" }, "the panel's severity words, not '2 problems'");
  assert.deepEqual(workProblemsLine(readProblems(payload(problem("a", "problem", "rule_denial")))), { text: "1 problem in Work", tone: "problem", target: "work" });
  assert.deepEqual(workProblemsLine(readProblems(payload(problem("a", "attention"), problem("b", "problem")))),
    { text: "1 problem and 1 needing attention in Work", tone: "problem", target: "work" });
});

test("Knowledge syncs are not counted as Work problems; alone they are named as Knowledge problems", () => {
  const syncs = [problem("s1", "attention", "sync"), problem("s2", "attention", "sync")];
  assert.deepEqual(workProblemsLine(readProblems(payload(...syncs))), { text: "2 Knowledge problems", tone: "attention", target: "knowledge" });
  assert.deepEqual(workProblemsLine(readProblems(payload(...syncs, problem("a", "attention")))),
    { text: "1 needs attention in Work", tone: "attention", target: "work" }, "Work problems first, without the syncs");
  assert.equal(workProblemsLine(readProblems(payload(problem("t", "problem", "token"), problem("d", "attention", "device")))), null,
    "tokens and devices have their own pages");
});

test("operations detectors: run problems and a stalled device job count in Work; other device problems do not", () => {
  const looping = { ...problem("run:r1:looping", "problem", "run"), count: 38 };
  const stalled = { ...problem("device:dj_1:job_stalled", "problem", "device"), object: { type: "device_job", id: "dj_1", name: "core-domain" } };
  const offline = { ...problem("device:dev_1:offline", "attention", "device"), object: { type: "device", id: "dev_1", name: "Mac" } };
  assert.deepEqual(workProblemsLine(readProblems(payload(looping, stalled, offline))), { text: "2 problems in Work", tone: "problem", target: "work" });
  assert.equal(workProblemsLine(readProblems(payload(offline))), null);
});

function makeLoader(stubs, sandbox) {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, { exports, ...sandbox, require: (name) => resolve(name, path.dirname(file)) });
    return exports;
  };
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (!name.startsWith(".")) return require(name);
    const base = path.resolve(dir, name);
    const file = [".tsx", ".ts"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate));
    return load(file);
  };
  return (relative) => load(path.join(SRC, relative));
}

async function render(handler) {
  const calls = [];
  const fetch = async (url) => {
    calls.push(url);
    const [status, body] = handler(url);
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  const sandbox = {
    fetch, console, Error, Promise, Set, Map, URLSearchParams, setTimeout, clearTimeout,
    window: { innerWidth: 1400, addEventListener() {}, removeEventListener() {}, location: { search: "" } },
    document: { addEventListener() {}, removeEventListener() {}, activeElement: null },
  };
  const stubs = {
    "/workflowSurfaces/ActionMenu": { ActionMenu: () => null },
    "/problems/ProblemsView": { WorkspaceProblems: ({ workspaceId }) => createElement("div", { "data-testid": "workspace-problems" }, workspaceId) },
  };
  const { WorkProblemsLine } = makeLoader(stubs, sandbox)("chat/work/WorkProblemsLine.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkProblemsLine, { workspaceId: "ws_1" })); });
  await act(async () => {});
  return { view, calls };
}

const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

test("rendered: the line shows the count and Show opens the Workspace's problems in the side panel", async () => {
  const { view, calls } = await render(() => [200, payload(problem("a", "problem"), problem("b", "attention"), problem("c", "attention"))]);
  assert.deepEqual(calls, ["/api/v1/workspaces/ws_1/problems"]);
  const line = byTestId(view, "work-problems-line");
  assert.equal(line.length, 1);
  assert.match(text(line[0]), /^1 problem and 2 needing attention in Work · Show$/);
  assert.match(line[0].props.className, /--problem/);
  assert.equal(byTestId(view, "workspace-problems").length, 0, "the panel opens only on Show");
  const show = line[0].findAll((node) => node.type === "button")[0];
  await act(async () => show.props.onClick());
  assert.equal(byTestId(view, "workspace-problems").length, 1);
  assert.equal(text(byTestId(view, "workspace-problems")[0]), "ws_1");
});

test("rendered: no line without problems, on 404 and on an error", async () => {
  for (const handler of [
    () => [200, payload()],
    () => [404, { detail: { code: "workspace_not_found", message: "x" } }],
    () => { throw new Error("offline"); },
  ]) {
    const { view } = await render(handler);
    assert.equal(byTestId(view, "work-problems-line").length, 0);
  }
});

test("rendered: only Knowledge problems link to Knowledge instead of opening the Work panel", async () => {
  const { view } = await render(() => [200, payload(problem("s1", "attention", "sync"), problem("s2", "problem", "sync"))]);
  const line = byTestId(view, "work-problems-line")[0];
  assert.match(text(line), /^2 Knowledge problems · Open Knowledge$/);
  assert.equal(byTestId(view, "work-problems-knowledge")[0].props.href, "/chat?area=knowledge&tab=knowledgeSources&workspace_id=ws_1");
});
