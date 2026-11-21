// The single-step publish under the single-admin approval rule (prompt catalog); four-eyes keeps submit/request
// approval and the approval ID.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { createPromptCatalogApi } from "../../src/admin/components/promptCatalog/promptCatalogApi.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const rule = (selfApprovalAllowed) => ({ useApprovalRule: () => ({ selfApprovalAllowed }) });

function load(path, name, mocks) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/admin/components/${path}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, {
    exports, encodeURIComponent,
    require(spec) {
      const key = Object.keys(mocks).find((suffix) => spec.endsWith(suffix));
      return key ? mocks[key] : require(spec);
    },
  });
  return exports[name];
}

const labels = (view) => view.root.findAll((node) => node.type === "button").map((b) => [].concat(b.props.children).join(""));
const button = (view, label) => view.root.find((node) => node.type === "button" && [].concat(node.props.children).join("") === label);

function renderActions(selfApprovalAllowed, state, extra = {}) {
  const Actions = load("promptCatalog/PromptVersionActions.tsx", "PromptVersionActions", {
    approvalRule: rule(selfApprovalAllowed),
    approvalDetailModel: { approvalDetailHref: (id) => `/approval/${id}` },
  });
  const calls = [];
  const model = {
    busy: null, showDiff: () => {},
    submit: (id) => calls.push(["submit", id]),
    publish: (id, approvalId) => calls.push(["publish", id, approvalId]),
    publishSelfApproved: (id, versionState) => calls.push(["self", id, versionState]),
    approve: (id) => calls.push(["approve", id]),
    reject: (id) => calls.push(["reject", id]),
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(Actions, { model, version: { id: "v1", version: 2, state, approval_id: null, ...extra.version }, currentUserId: extra.currentUserId ?? "", risk: "high" })); });
  return { view, calls };
}

test("prompt catalog, single admin: one Publish submits and self-approves; no approval ID field", () => {
  const { view, calls } = renderActions(true, "draft");
  assert.ok(labels(view).includes("Publish"));
  assert.ok(!labels(view).includes("Submit for four-eyes review"));
  act(() => button(view, "Publish").props.onClick());
  assert.deepEqual(calls, [["self", "v1", "draft"]]);
  const inReview = renderActions(true, "in_review").view;
  assert.equal(inReview.root.findAll((node) => node.props["aria-label"] === "Approval id").length, 0);
  assert.ok(labels(inReview).includes("Publish"));
});

test("prompt catalog, four-eyes: submit for review, then publish with a pasted approval", () => {
  const draft = renderActions(false, "draft");
  assert.ok(labels(draft.view).includes("Submit for four-eyes review"));
  assert.ok(!labels(draft.view).includes("Publish"));
  const inReview = renderActions(false, "in_review").view;
  assert.equal(inReview.root.findAll((node) => node.props["aria-label"] === "Approval id").length, 1);
  assert.ok(labels(inReview).includes("Publish with approval"));
});

test("prompt catalog, four-eyes: the second person approves at the version, the author does not see Approve", () => {
  const reviewer = renderActions(false, "in_review", { version: { approval_id: "ap-1", created_by: "author" }, currentUserId: "reviewer" });
  assert.ok(labels(reviewer.view).includes("Approve"));
  act(() => button(reviewer.view, "Approve").props.onClick());
  assert.deepEqual(reviewer.calls, [["approve", "ap-1"]]);
  const author = renderActions(false, "in_review", { version: { approval_id: "ap-1", created_by: "author" }, currentUserId: "author" });
  assert.ok(!labels(author.view).includes("Approve"));
  // After the submit the approval id is already filled in for publishing.
  const field = author.view.root.find((node) => node.props["aria-label"] === "Approval id");
  assert.equal(field.props.value, "ap-1");
});

test("the prompt publish request carries self_approve only for the single-step publish", async () => {
  const bodies = [];
  const api = createPromptCatalogApi(async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ version: {}, approval_gate: { status: "approved", approval_mode: "self" } }), { status: 200 });
  });
  await api.publish("v1", null, true);
  await api.publish("v1", "ap-1");
  assert.deepEqual(bodies, [{ self_approve: true }, { governance_approval_id: "ap-1" }]);
});
