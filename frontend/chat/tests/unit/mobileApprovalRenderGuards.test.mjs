// Render guard for the phone approval page: the status, the preview, the decision buttons, the deny form, the
// outcome and the read-only states stay the same when the page is split into smaller parts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, load, noop, render, text } from "./renderGuardHarness.mjs";

const byTestId = (root, id) => root.findAll((node) => typeof node.type === "string" && node.props?.["data-testid"] === id);
const byClass = (root, name) => root.findAll((node) => typeof node.type === "string"
  && typeof node.props?.className === "string" && node.props.className.split(" ").includes(name));

function loadPage(decided) {
  return load("mobile/ApprovalPage.tsx", {
    icons: { Icon: (p) => createElement("i", { "data-icon": p.name }) },
    mobileApi: { decideApproval: async (...args) => { decided.push(args); } },
    mobileUsageModel: { shortTime: () => "5 min" },
    PageHeader: { DetailHeader: (p) => createElement("header", { "data-testid": "detail-header" }, p.title, p.subtitle ?? "") },
    WritePlanApprovalCard: { PlanScope: box("plan-scope"), Writes: box("writes") },
    RedactedText: { RedactedText: (p) => p.value },
  }).ApprovalPage;
}

const approval = {
  id: "a1", action: "run", sessionId: "s1", workflowRunId: null, workspaceId: "w", requestedBy: "u", requestedByName: "Anna",
  createdAt: "2026-01-01T00:00:00Z", payload: { summary: "Run git status", command: "git status", details: ["one", "two"] },
  preview: "generic", title: "Run a command", subtitle: "Because", details: null, governance: false,
  decisions: [{ kind: "reject", label: "Deny" }, { kind: "approve", label: "Allow once" }],
};
const pageProps = (settled, opened) => ({
  workspace: "Demo", onBack: noop, onSettled: () => settled.push(1), onOpenRun: (...a) => opened.push(["run", ...a]),
  onOpenChat: (...a) => opened.push(["chat", ...a]),
});

test("a waiting approval shows what is asked, who asked, the preview and both decisions", async () => {
  const decided = [];
  const settled = [];
  const opened = [];
  const ApprovalPage = loadPage(decided);
  const view = await render(ApprovalPage, { ...pageProps(settled, opened), approval });
  const root = view.root;
  assert.equal(text(byTestId(root, "detail-header")[0]), "ApprovalDemo");
  assert.equal(byTestId(root, "m-approval")[0].props["aria-label"], "Approval: Run a command");
  assert.equal(text(byTestId(root, "m-approval-status")[0]), "Waiting for you");
  assert.equal(text(byTestId(root, "m-approval-subtitle")[0]), "Because");
  assert.deepEqual(byClass(root, "m-muted").map(text), ["Demo · Anna · 5 min ago", "Only this request. The next one asks again."]);
  assert.equal(text(byClass(root, "m-plan-pre")[0]), "git status");
  assert.deepEqual(byClass(root, "m-plan-lines")[0].findAllByType("li").map(text), ["one", "two"]);
  act(() => byTestId(root, "m-approval-link")[0].props.onClick());
  assert.deepEqual(opened, [["chat", "s1", "Run a command"]]);
  assert.equal(text(byTestId(root, "m-approval-reject")[0]), "Deny");
  assert.equal(text(byTestId(root, "m-approval-approve")[0]), "Allow once");

  act(() => byTestId(root, "m-approval-reject")[0].props.onClick());
  assert.equal(byTestId(root, "m-approval-reject").length, 0);
  act(() => byTestId(root, "m-approval-reason")[0].props.onChange({ target: { value: "Not now" } }));
  assert.deepEqual(byClass(root, "m-buttons")[0].findAllByType("button").map(text), ["Cancel", "Deny"]);
  await act(async () => root.findByType("form").props.onSubmit({ preventDefault: noop }));
  assert.equal(JSON.stringify(decided), JSON.stringify([["a1", "reject", "Not now"]]));
  assert.equal(settled.length, 1);
  assert.equal(text(byTestId(root, "m-approval-status")[0]), "Denied");
  assert.equal(text(byTestId(root, "m-approval-outcome")[0]), "Denied. Your reason goes with it: “Not now”");
  assert.equal(byClass(root, "m-buttons").length, 0);
});

test("an approved write plan, a run link and the read-only states read in words", async () => {
  const decided = [];
  const opened = [];
  const ApprovalPage = loadPage(decided);
  const plan = { ...approval, preview: "plan", payload: { request: "x", writes: [] }, workflowRunId: "r1" };
  const view = await render(ApprovalPage, { ...pageProps([], opened), approval: plan });
  const root = view.root;
  assert.equal(text(byTestId(root, "m-approval-link")[0]), "Open the run");
  act(() => byTestId(root, "m-approval-link")[0].props.onClick());
  assert.deepEqual(opened, [["run", "r1", "Run a command"]]);
  await act(async () => byTestId(root, "m-approval-approve")[0].props.onClick());
  assert.equal(JSON.stringify(decided), JSON.stringify([["a1", "approve", ""]]));
  assert.equal(text(byTestId(root, "m-approval-status")[0]), "Approved");

  const governance = { ...approval, governance: true, decisions: [], preview: "other", payload: null, sessionId: null };
  const readOnly = (await render(ApprovalPage, { ...pageProps([], []), approval: governance })).root;
  assert.equal(text(byTestId(readOnly, "m-approval-readonly")[0]), "A governance review is decided on its publishing page in the web app.");
  assert.equal(byTestId(readOnly, "m-approval-link").length, 0);
  assert.deepEqual(byClass(readOnly, "m-muted").map(text), ["Demo · Anna · 5 min ago", "run",
    "A governance review is decided on its publishing page in the web app."]);
});
