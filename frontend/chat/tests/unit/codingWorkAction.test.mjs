// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingWorkAction.test.mjs
//
// Guided Coding-to-Work handoff. A blocked session names what Work needs and links the exact
// latest plan by work_item_id + change_plan_id; runtime blockers are never presented as solved by a
// plan; stale or loading detail never names a plan; Start agent eligibility is unchanged.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { buildCodingSessionSummary } from "../../src/chat/coding/codingSessionModel.ts";
import { codingWorkAction, exactPlanHref, listEntries } from "../../src/chat/coding/codingWorkActionModel.ts";
import { readCssWithImports } from "./cssWithImports.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, URL, URLSearchParams, Intl, console, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

const Null = () => null;
const loadModule = makeLoader({
  "/CodingAuditPanel": { CodingAuditPanel: Null },
  "/CodingPipelineTracePanel": { CodingPipelineTracePanel: Null },
  "/CodingRuntimeObservability": { RuntimeObservabilityDeepDive: Null, RuntimeObservabilitySummary: Null },
  "/CodingReviewWorkspace": { CodingReviewWorkspace: Null },
  "/CodingWorkspaceEvidence": { CodingWorkspaceEvidence: Null },
  "/CodingGovernanceKit": { GovernanceMetrics: Null },
});

// An id that needs encoding, so the exact address is checked byte for byte.
const ITEM_ID = "ops 2/#a";

function item(sourceFields = {}, overrides = {}) {
  return {
    id: ITEM_ID, source_key: "OPS-2", title: "Synthetic operations item", description: "", source_status: "Open",
    work_state: "planning", sync_state: "imported", labels: [], fix_versions: [], components: [], linked_issues: [],
    source_fields: sourceFields, source_url: null, automation_eligibility: null, ...overrides,
  };
}

function plan(overrides = {}) {
  return {
    id: "plan-v2", work_item_id: ITEM_ID, version: 2, status: "needs_clarification", title: "Clarify operations change",
    understood_request: "", assumptions: [], open_questions: [], affected_repositories: [], change_units: [],
    proposed_branches: [], planned_files: [], validation_plan: [], acceptance_criteria: [], security_risks: [],
    reviewer_recommendations: [], required_approvals: [], expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {},
    jira_sync_preview: {}, created_by: "u1", ...overrides,
  };
}

function scenario({ sourceFields = {}, plans = [plan()], itemOverrides = {}, stateEvents = [] } = {}) {
  const workItem = item(sourceFields, itemOverrides);
  const session = buildCodingSessionSummary({ item: workItem, changePlans: plans, stateEvents });
  const detail = {
    workItem, changePlans: plans, changeUnits: [], reviewerPayload: null, stateEvents, pipelineTrace: null,
    reviewEventsPayload: null, auditReport: null, cicdPipelineTraces: null, cicdFindings: null, observability: null,
  };
  return { session, detail };
}

const V1_APPROVED = plan({ id: "plan-v1", version: 1, status: "approved", open_questions: [] });

// ---- model -----------------------------------------------------------------------------------

test("clarification: the exact latest plan (v2) is linked with its questions, never the approved v1", () => {
  const v2 = plan({ open_questions: ["Which cluster is in scope?", "Who signs off the change window?"] });
  const { session, detail } = scenario({ plans: [V1_APPROVED, v2] });
  // A plan's open questions are planning work, not a blocked Coding run.
  assert.equal(session.state, "planned");
  const action = codingWorkAction(session, detail, false);
  assert.equal(action.state, "plan");
  assert.equal(action.title, "Plan v2 has open questions");
  assert.equal(action.planAction.href, "/chat?area=work&work_item_id=ops%202%2F%23a&change_plan_id=plan-v2");
  assert.equal(action.planAction.href, exactPlanHref(ITEM_ID, "plan-v2"));
  assert.doesNotMatch(action.planAction.href, /plan-v1/);
  assert.deepEqual(action.questions.shown, ["Which cluster is in scope?", "Who signs off the change window?"]);
  assert.match(action.startHint, /stays unavailable until plan v2 or a newer version is approved/);
  // The exact latest plan with questions is answered in Work, not replaced by hand.
  assert.equal(action.planAction.label, "Answer open questions (v2)");
  assert.match(action.message, /^Answer the open questions on plan v2 in Work, then use Generate v3 from answers\./);
  assert.match(action.message, /Unanswered questions stay open in the new version, and a reviewer then decides on it\./);
  assert.match(action.message, /Answers do not change repository or reviewer setup/);
  assert.doesNotMatch(action.message, /New version/);
});

test("clarification without recorded questions keeps the review path; other statuses are unchanged", () => {
  // A reviewer's "Clarify" can leave needs_clarification without questions: Work shows no answer field.
  const requested = codingWorkAction(...Object.values(scenario({ plans: [plan({ open_questions: [] })] })), false);
  assert.equal(requested.title, "Plan v2 has open questions");
  assert.equal(requested.planAction.label, "Review open questions (v2)");
  assert.match(requested.message, /create a new plan version there with New version/);
  assert.doesNotMatch(requested.message, /answer/i);

  const blocked = scenario({ plans: [plan({ open_questions: ["Which cluster?"] })], sourceFields: { blockers: ["Repository profile missing"] } });
  const withBlockers = codingWorkAction(blocked.session, blocked.detail, false);
  assert.deepEqual(withBlockers.blockers.shown, ["Repository profile missing"], "configuration blockers stay listed apart");
  assert.match(withBlockers.startHint, /stays unavailable until plan v2 or a newer version is approved/);

  for (const [status, label] of [["ready_for_review", "Review plan (v2)"], ["draft", "Open draft plan (v2)"], ["rejected", "Open rejected plan (v2)"]]) {
    const { session, detail } = scenario({ plans: [plan({ status, open_questions: ["Still open?"] })] });
    const action = codingWorkAction(session, detail, false);
    assert.equal(action.planAction.label, label, status);
    assert.doesNotMatch(action.message, /answer/i, status);
  }
});

test("rejected and ready-for-review plans link the exact plan; a review wait is not a blocked session", () => {
  const rejected = scenario({ plans: [plan({ id: "plan-v3", version: 3, status: "rejected" })] });
  // A rejected plan ends that plan, not the Work Item.
  assert.equal(rejected.session.state, "planned", "a rejected latest plan is not a cancelled item");
  const rejectedAction = codingWorkAction(rejected.session, rejected.detail, false);
  assert.equal(rejectedAction.planAction.label, "Open rejected plan (v3)");
  assert.equal(rejectedAction.planAction.href, exactPlanHref(ITEM_ID, "plan-v3"));
  // Rejected is final: only a new, approved version can unblock Start agent.
  assert.equal(rejectedAction.startHint, "Start agent stays unavailable until a new plan version is created and approved.");
  assert.doesNotMatch(rejectedAction.startHint, /v3/);
  assert.match(rejectedAction.message, /cannot be approved/);

  const review = scenario({ plans: [plan({ status: "ready_for_review" })] });
  assert.equal(review.session.state, "planned", "Work Plan review is not delivery review; Start agent needs an approved plan");
  const reviewAction = codingWorkAction(review.session, review.detail, false);
  assert.equal(reviewAction.state, "plan");
  assert.equal(reviewAction.planAction.label, "Review plan (v2)");
});

test("missing plan: the fact is stated and only the Work Item is offered", () => {
  const { session, detail } = scenario({
    plans: [],
    sourceFields: { blockers: [{ message: "Jira ticket has no acceptance criteria" }] },
    itemOverrides: { work_state: "blocked" },
  });
  assert.equal(session.state, "blocked");
  const action = codingWorkAction(session, detail, false);
  assert.equal(action.state, "item");
  assert.equal(action.title, "No Change Plan yet");
  assert.equal(action.planAction, null);
  assert.equal(action.workItemHref, "/chat?area=work&work_item_id=ops%202%2F%23a");
  assert.deepEqual(action.blockers.shown, ["Jira ticket has no acceptance criteria"]);
});

test("runtime-blocked approved plan: blockers are listed, no plan link, never 'approve the plan to fix it'", () => {
  const { session, detail } = scenario({
    plans: [plan({ status: "approved" })],
    sourceFields: { blockers: [{ message: "npm run build failed in ops-repo" }, "Sandbox image unavailable"] },
  });
  assert.equal(session.state, "blocked");
  const action = codingWorkAction(session, detail, false);
  assert.equal(action.state, "item");
  assert.equal(action.planAction, null);
  assert.match(action.message, /already approved; approving a plan or creating a new version does not clear these blockers/);
  assert.deepEqual(action.blockers.shown, ["npm run build failed in ops-repo", "Sandbox image unavailable"]);
  assert.match(action.startHint, /while this session needs work/);
});

test("needs_replan on an approved plan links that exact plan for a new version", () => {
  const { session, detail } = scenario({ plans: [plan({ status: "approved" })], sourceFields: { requires_replan: true } });
  assert.equal(session.state, "needs_replan");
  const action = codingWorkAction(session, detail, false);
  assert.equal(action.state, "plan");
  assert.equal(action.title, "Plan v2 is approved but out of date");
  assert.equal(action.planAction.href, exactPlanHref(ITEM_ID, "plan-v2"));
});

test("stale or loading detail never names a plan", () => {
  const { session, detail } = scenario({ plans: [plan({ open_questions: ["q"] })] });
  for (const [label, staleDetail, loading] of [
    ["loading", detail, true],
    ["no detail yet", null, false],
    ["previous item's detail", { ...detail, workItem: { ...detail.workItem, id: "other-item" } }, false],
    ["another item's plans", { ...detail, workItem: null, changePlans: [plan({ id: "foreign", work_item_id: "other-item" })] }, false],
  ]) {
    const action = codingWorkAction(session, staleDetail, loading);
    assert.equal(action.state, "checking", label);
    assert.equal(action.planAction, null, label);
    assert.equal(action.questions.shown.length, 0, label);
  }
});

test("an ordinary planning item without any plan gets the no-plan guidance (root repro)", () => {
  const { session, detail } = scenario({ plans: [] });
  assert.equal(session.state, "draft");
  assert.equal(session.blockerCount, 0);
  const action = codingWorkAction(session, detail, false);
  assert.equal(action.state, "item");
  assert.equal(action.title, "No Change Plan yet");
  assert.match(action.message, /use Generate plan in its Change Plan section/);
  assert.equal(action.planAction, null);
  assert.equal(action.workItemHref, "/chat?area=work&work_item_id=ops%202%2F%23a");
  assert.match(action.startHint, /has none yet/);
  assert.equal(codingWorkAction(session, detail, true).state, "checking", "still safe while loading");
  assert.equal(codingWorkAction(session, null, false).state, "checking");
  // A detail that already shows a plan wins over a summary that has none yet.
  const withApproved = { ...detail, changePlans: [plan({ status: "approved" })] };
  assert.equal(codingWorkAction(session, withApproved, false).state, "hidden");
});

test("active and running sessions without a Work action stay hidden", () => {
  for (const workState of ["implementing", "testing", "in_review"]) {
    for (const plans of [[], [plan({ status: "approved" })]]) {
      const { session, detail } = scenario({ plans, itemOverrides: { work_state: workState } });
      assert.notEqual(session.state, "draft", workState);
      assert.equal(codingWorkAction(session, detail, false).state, "hidden", `${workState} with ${plans.length} plan(s)`);
    }
  }
});

test("approved/startable and completed sessions show no Work action", () => {
  const approved = scenario({ plans: [plan({ status: "approved" })] });
  assert.equal(approved.session.state, "approved");
  assert.equal(codingWorkAction(approved.session, approved.detail, false).state, "hidden");
  const done = scenario({ plans: [plan({ status: "approved" })], itemOverrides: { work_state: "done" } });
  assert.equal(done.session.state, "completed");
  assert.equal(codingWorkAction(done.session, done.detail, false).state, "hidden");
  const closedRejected = scenario({ plans: [plan({ status: "rejected" })], itemOverrides: { work_state: "cancelled" } });
  assert.equal(codingWorkAction(closedRejected.session, closedRejected.detail, false).state, "hidden", "a cancelled item stays closed");
});

test("lists stay short and honest: duplicates merged, overflow counted, unreadable entries reported", () => {
  const entries = ["a", "b", "a", { reason: "c" }, "d", "e", "f", "g", {}, 7];
  assert.deepEqual(listEntries(entries), { shown: ["a", "b", "c", "d", "e"], more: 2, unreadable: 2 });
});

// ---- rendered --------------------------------------------------------------------------------

function renderDetail(session, detail, loading = false) {
  const { CodingSessionDetail } = loadModule("CodingSessionDetail.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(CodingSessionDetail, {
      session, detail, loading, activeTab: "overview", startingAgent: false,
      onTabChange: () => {}, onStartAgent: () => {}, onRestartAgent: () => {},
    }));
  });
  return view;
}

const hrefs = (view) => view.root.findAll((node) => node.type === "a").map((node) => node.props.href);

test("rendered OPS-2: the panel opens exact v2 with its questions; Open Work Item and the Start policy stay", () => {
  const v2 = plan({ open_questions: ["Which cluster is in scope?"] });
  const { session, detail } = scenario({ plans: [V1_APPROVED, v2], sourceFields: { blockers: ["Sandbox image unavailable"] } });
  const view = renderDetail(session, detail);
  const panel = view.root.findByProps({ "aria-label": "Work action" });
  const panelText = text(panel);
  assert.match(panelText, /Plan v2 has open questions/);
  assert.match(panelText, /Which cluster is in scope\?/);
  assert.match(panelText, /Other recorded blockers \(not resolved by the plan\)Sandbox image unavailable/);
  const panelLinks = panel.findAll((node) => node.type === "a");
  assert.deepEqual(panelLinks.map((node) => node.props.href), [exactPlanHref(ITEM_ID, "plan-v2")]);
  assert.equal(text(panelLinks[0]), "Answer open questions (v2)");
  assert.ok(hrefs(view).includes("/chat?area=work&work_item_id=ops%202%2F%23a"), "generic Open Work Item link kept");
  assert.ok(!hrefs(view).some((href) => href.includes("plan-v1")), "the approved v1 is never offered");
  // The session is planning (open questions), so the header offers Start agent, disabled
  // because the latest plan is not approved; the Work action panel above says what to do.
  const start = view.root.findAll((node) => node.type === "button" && text(node) === "Start agent");
  assert.equal(start.length, 1);
  assert.equal(start[0].props.disabled, true, "Start agent eligibility is unchanged");
  act(() => view.unmount());
});

test("rendered: loading detail shows a busy notice and no plan link; startable sessions show none", () => {
  const { session, detail } = scenario({ plans: [plan({ open_questions: ["q"] })] });
  const loadingView = renderDetail(session, detail, true);
  const panel = loadingView.root.findByProps({ "aria-label": "Work action" });
  assert.equal(panel.props["aria-busy"], "true");
  assert.equal(panel.findAll((node) => node.type === "a").length, 0);
  act(() => loadingView.unmount());

  const approved = scenario({ plans: [plan({ status: "approved" })] });
  const approvedView = renderDetail(approved.session, approved.detail);
  assert.equal(approvedView.root.findAll((node) => node.props?.["aria-label"] === "Work action").length, 0);
  const start = approvedView.root.findAll((node) => node.type === "button" && text(node) === "Start agent");
  assert.equal(start[0].props.disabled, false);
  act(() => approvedView.unmount());
});

test("rendered no-plan draft: the panel explains the disabled Start agent and offers the Work Item", () => {
  const { session, detail } = scenario({ plans: [] });
  const view = renderDetail(session, detail);
  const panel = view.root.findByProps({ "aria-label": "Work action" });
  assert.match(text(panel), /No Change Plan yet/);
  assert.deepEqual(panel.findAll((node) => node.type === "a").map((node) => node.props.href), [
    "/chat?area=work&work_item_id=ops%202%2F%23a",
  ]);
  const start = view.root.findAll((node) => node.type === "button" && text(node) === "Start agent");
  assert.equal(start[0].props.disabled, true, "Start agent eligibility is unchanged");
  act(() => view.unmount());
});

// ---- destination affordances -------------------------------------------------------------------

// The Work plan view: the plan list with its actions and the selected plan's view.
const WORK_PLANS_SOURCE = ["WorkChangePlans.tsx", "WorkChangePlanView.tsx"]
  .map((file) => fs.readFileSync(path.resolve(CODING_DIR, `../work/${file}`), "utf8")).join("\n");
const WORK_DETAIL_SOURCE = fs.readFileSync(path.resolve(CODING_DIR, "../work/WorkItemDetailPanel.tsx"), "utf8");
const WORK_ANSWERS_SOURCE = fs.readFileSync(path.resolve(CODING_DIR, "../work/WorkPlanClarificationAnswers.tsx"), "utf8");

function allGuidance() {
  const cases = [
    scenario({ plans: [plan({ status: "needs_clarification", open_questions: ["q"] })] }),
    scenario({ plans: [plan({ status: "ready_for_review" })] }),
    scenario({ plans: [plan({ status: "rejected" })] }),
    scenario({ plans: [plan({ status: "draft" })] }),
    scenario({ plans: [plan({ status: "approved" })], sourceFields: { requires_replan: true } }),
    scenario({ plans: [plan({ status: "approved" })], sourceFields: { blockers: ["x"] }, itemOverrides: { work_state: "blocked" } }),
    scenario({ plans: [] }),
  ];
  return cases.map(({ session, detail }) => codingWorkAction(session, detail, false));
}

test("guidance promises only what the Work plan view really offers", () => {
  // The Work plan view's real controls: Generate plan / New version, and for a plan that is not
  // final the reviewer decisions Approve vN, Clarify and Reject; an exact plan is placed on top.
  for (const control of [/"New version"/, /"Generate plan"/, /Approve v\{selected\.version\}/, />\s*Clarify\s*</, />\s*Reject\s*</]) {
    assert.match(WORK_PLANS_SOURCE, control);
  }
  assert.match(WORK_PLANS_SOURCE, /FINAL_PLAN_STATUSES\.has\(selected\.status\)/, "final statuses come from planStatus.ts (D14)");
  assert.match(WORK_DETAIL_SOURCE, /\{focusPlanId \? changePlanSection : null\}/, "an exact plan opens at the top of Work");
  // The plan view hosts the answer form for its open questions, with one field per question
  // and the "Generate v{n+1} from answers" button; no draft editor or send-for-review exists.
  assert.match(WORK_PLANS_SOURCE, /<WorkPlanClarificationAnswers plan=\{selected\}/);
  assert.match(WORK_ANSWERS_SOURCE, /<textarea/);
  assert.match(WORK_ANSWERS_SOURCE, /`Generate v\$\{plan\.version \+ 1\} from answers`/);
  assert.doesNotMatch(WORK_PLANS_SOURCE + WORK_ANSWERS_SOURCE, /send for review|submit answers/i);
  const actions = allGuidance();
  assert.equal(actions.filter((action) => action.state === "hidden").length, 0);
  for (const action of actions) {
    const words = [action.title, action.message, action.startHint, action.planAction?.label || ""].join(" ");
    assert.doesNotMatch(words, /send (it )?for review|complete the plan|\bedit/i, words);
    // Answering is promised only for a plan with recorded questions, and names the real button.
    if (/\banswer/i.test(words)) {
      assert.ok(action.questions.shown.length > 0, words);
      assert.match(action.message, /Generate v\d+ from answers/);
    }
    if (/New version/.test(action.message)) assert.ok(WORK_PLANS_SOURCE.includes('"New version"'));
    if (/Generate plan/.test(action.message)) assert.ok(WORK_PLANS_SOURCE.includes('"Generate plan"'));
  }
});

// ---- layout (live review: the panel squeezed the tabs to 18.59px) ---------------------------

const CODING_CSS = readCssWithImports(path.resolve(CODING_DIR, "../../styles/chat/coding-detail.css"));

function cssBlock(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = CODING_CSS.match(new RegExp(`(^|\\n)${escaped} \\{([^}]*)\\}`));
  assert.ok(match, `CSS rule ${selector}`);
  return match[2];
}

test("the detail grid keeps exactly header and scrolling body; the panel lives inside the body", () => {
  const v2 = plan({ open_questions: Array.from({ length: 9 }, (_, index) => `Question ${index + 1} ${"long text ".repeat(20)}`) });
  const { session, detail } = scenario({ plans: [V1_APPROVED, v2], sourceFields: { blockers: ["Sandbox image unavailable"] } });
  for (const loading of [false, true]) {
    const view = renderDetail(session, detail, loading);
    const section = view.root.findByProps({ className: "coding-detail" });
    // A component child counts as the element it renders (the header is CodingSessionHeader).
    const host = (child) => (typeof child.type === "string" ? child : host(child.children.find((entry) => typeof entry !== "string")));
    const gridChildren = section.children.filter((child) => typeof child !== "string").map(host);
    assert.deepEqual(
      gridChildren.map((child) => `${child.type}.${child.props.className}`),
      ["header.coding-detail__header", "div.coding-detail__body"],
      "two grid rows: the notice must not become a row of its own",
    );
    const body = gridChildren[1];
    const panel = body.findByProps({ "aria-label": "Work action" });
    assert.equal(panel.props.className, "coding-execution-notice coding-work-action");
    // Boolean checks only: a failing equality between test instances would dump the whole fiber graph.
    const first = body.children.filter((child) => typeof child !== "string")[0];
    assert.ok(first === panel || first.findAll((node) => node === panel).length === 1, "the notice is the first thing in the body");
    act(() => view.unmount());
  }
});

test("CSS contract: two-row detail grid, scrolling body, one-line CTA scoped to the Work action", () => {
  assert.match(cssBlock(".coding-detail"), /grid-template-rows: auto minmax\(0, 1fr\);/);
  const body = cssBlock(".coding-detail__body");
  assert.match(body, /min-height: 0;/);
  assert.match(body, /overflow: auto;/);
  assert.match(cssBlock(".coding-work-action .coding-execution-notice__actions"), /flex: none;/);
  assert.match(cssBlock(".coding-work-action .coding-execution-notice__actions .work-area__button"), /white-space: nowrap;/);
  assert.match(cssBlock(".coding-work-action li"), /overflow-wrap: anywhere;/);
  // The shared notice used by other Coding notices keeps its layout.
  assert.doesNotMatch(cssBlock(".coding-execution-notice__actions"), /flex: none|nowrap/);
});
