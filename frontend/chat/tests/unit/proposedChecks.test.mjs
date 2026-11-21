// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/proposedChecks.test.mjs
// Work › Coding rules › Proposed checks:
// what the panel says and lets a person do. Four-eyes: who changed a proposal does not approve it; approving without a
// proof is an explicit choice; rejecting needs a reason; every message shows what to do instead.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { approveBlocker, evidenceText, proofStatus, stateStatus } from "../../src/chat/coding/governance/proposedChecksModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const PROPOSAL = {
  id: "chp_timeout", state: "proposed",
  evidence: { repeats: 3, runs: 3, sources: { review_fixed: 2, pipeline_cause: 1 },
    occurrences: [{ source: "review_fixed", work_item_key: "OCX-7", at: "2026-11-17T09:12:00Z", excerpt: "No timeout on the payment call." }] },
  draft: { kind: "lint_rule", lands_in: "code_style:stack:python", rule: { tool: "ruff", rule_id: "S113" }, summary: "Every HTTP call names a timeout." },
  message: { what: "An HTTP call without a timeout.", why: "It hangs the worker.", instead: "Pass timeout=10." },
  old_instances: { count: 4, examples: [{ path: "shop/payments.py", line: 41 }] },
  proof: { state: "proven", red_on: [{ commit: "9f3c2a1" }, { commit: "b71e0d4" }], green_on: { commit: "e04a9c7", files_checked: 42 } },
  severity: "warning", enabled: true, edits: [], decision: null, updated_at: "2026-11-19T10:00:00Z",
};

test("the list says why, how proven and in what state, in words", () => {
  assert.equal(evidenceText(PROPOSAL), "3× in 3 runs · fixed in review 2, pipeline failure 1");
  assert.deepEqual([proofStatus(PROPOSAL.proof).label, proofStatus(PROPOSAL.proof).title],
    ["Proven", "Red on 2 past changes, green on 42 clean files."]);
  assert.equal(proofStatus({ state: "running", red_on: [], green_on: null }).label, "Proving");
  assert.equal(stateStatus({ state: "approved", enabled: true, severity: "warning" }).label, "Approved · warning");
  assert.equal(stateStatus({ state: "approved", enabled: false, severity: "warning" }).label, "Switched off");
  assert.equal(approveBlocker(PROPOSAL, "u-2", true), "");
  assert.match(approveBlocker({ ...PROPOSAL, edits: [{ by: "u-2", at: "", fields: [] }] }, "u-2", true), /second person/);
  assert.match(approveBlocker(PROPOSAL, "u-2", false), /approver permission/);
});

function panelWith(proposal, { viewerId = "u-2", mayApprove = true } = {}) {
  const posts = [];
  const fetch = async (url, init) => {
    if (init?.method === "POST") {
      posts.push({ url: String(url), body: JSON.parse(init.body) });
      const state = String(url).endsWith("/approve") ? "approved" : String(url).endsWith("/reject") ? "rejected" : proposal.state;
      return { ok: true, status: 200, json: async () => ({ ...proposal, state, decision: { state, by: viewerId, at: "", reason: "" } }) };
    }
    return { ok: true, status: 200, json: async () => proposal };
  };
  const document = { activeElement: null, addEventListener() {}, removeEventListener() {} };
  const { ProposedCheckPanel } = load("chat/coding/governance/ProposedCheckPanel.tsx", { fetch, document });
  let view;
  const changed = [];
  act(() => { view = TestRenderer.create(createElement(ProposedCheckPanel, { workspaceId: "ws-1", id: proposal.id, viewerId,
    mayApprove, onClose() {}, onChanged: () => changed.push(1) })); });
  return { get view() { return view; }, posts, changed };
}

test("an approver sees the evidence, the message with what to do instead, and approves a proven check", async () => {
  const panel = panelWith(PROPOSAL);
  await tick();
  assert.match(text(byTestId(panel.view, "proposed-check-body")[0]), /Why: 3× in 3 runs/);
  assert.equal(text(byTestId(panel.view, "proposed-check-message-instead")[0]), "Pass timeout=10.");
  await act(async () => { byTestId(panel.view, "proposed-check-approve")[0].props.onClick(); });
  assert.deepEqual(panel.posts, [{ url: "/api/v1/workspaces/ws-1/check-proposals/chp_timeout/approve", body: { accept_unproven: false, note: "" } }]);
  assert.equal(panel.changed.length, 1);
});

test("who changed it does not get Approve; an unproven check needs the explicit choice and a note", async () => {
  const own = panelWith({ ...PROPOSAL, edits: [{ by: "u-2", at: "", fields: ["message.instead"] }] });
  await tick();
  assert.equal(byTestId(own.view, "proposed-check-approve").length, 0);
  assert.match(text(byTestId(own.view, "proposed-check-blocker")[0]), /second person/);
  const unproven = panelWith({ ...PROPOSAL, proof: { state: "running", red_on: [], green_on: null } });
  await tick();
  assert.equal(byTestId(unproven.view, "proposed-check-approve")[0].props.disabled, true);
  await act(async () => { byTestId(unproven.view, "proposed-check-unproven")[0].props.onChange({ target: { checked: true } }); });
  assert.equal(byTestId(unproven.view, "proposed-check-approve")[0].props.disabled, true, "the note is still missing");
  await act(async () => { byTestId(unproven.view, "proposed-check-note")[0].props.onChange({ target: { value: " Obvious from three reviews. " } }); });
  assert.equal(byTestId(unproven.view, "proposed-check-approve")[0].props.disabled, false);
  await act(async () => { byTestId(unproven.view, "proposed-check-approve")[0].props.onClick(); });
  assert.deepEqual(unproven.posts[0].body, { accept_unproven: true, note: "Obvious from three reviews." });
});

test("rejecting asks why and sends the reason", async () => {
  const panel = panelWith(PROPOSAL);
  await tick();
  await act(async () => { byTestId(panel.view, "proposed-check-reject")[0].props.onClick(); });
  assert.equal(byTestId(panel.view, "proposed-check-reject-confirm")[0].props.disabled, true, "no reason yet");
  await act(async () => { byTestId(panel.view, "proposed-check-reason")[0].props.onChange({ target: { value: "We keep TODOs with a key." } }); });
  const form = panel.view.root.findAll((node) => node.type === "form")[0];
  await act(async () => { form.props.onSubmit({ preventDefault() {} }); });
  assert.deepEqual(panel.posts[0], { url: "/api/v1/workspaces/ws-1/check-proposals/chp_timeout/reject", body: { reason: "We keep TODOs with a key." } });
});
