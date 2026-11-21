// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/decisionCard.test.mjs
//
// UX audit (Alex OK on the mock): a product owner's decision shows the verdict as heading, one answer field
// per finding and per open question, and the primary action follows the verdict ("changes" → another round, never
// "Ship it" as the bright button). The fields join into the one text the change action posts.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  answeredCount,
  composeAnswer,
  decisionCard,
  decisionLabel,
  decisionPrimary,
  findingPlace,
  questionsInNote,
} from "../../src/chat/workflowRun/decisionCardModel.ts";
import { runNextAction, runSteps } from "../../src/chat/workflowRun/runCardModel.ts";

const ACTIONS = [
  { key: "confirm", label: "Ship it: push and open the pull request", input: null },
  { key: "change", label: "Send my answers to the agent",
    input: { name: "reason", kind: "text", default: "", label: "Your answers", required: true, max_length: 8000 } },
  { key: "stop", label: "Stop", tone: "danger", input: null },
];

function reviewWaiting(verdict, findings = [], assumptions = []) {
  return {
    kind: "awaiting_confirmation",
    subject: "decisions",
    payload: { subject: "decisions", shows: "review_verdict",
      output: { verdict, summary: "One shared counter.", findings, ...(assumptions.length ? { assumptions } : {}) } },
  };
}

const FINDINGS = [
  { severity: "medium", file: "tests/test_router.py", line: 12, fix: "Add a test for Retry-After." },
  { severity: "high", file: "src/app/router.py", line: 96, fix: "Key the counter by client id." },
];

test("the review card puts the verdict on top and sorts findings by severity", () => {
  const card = decisionCard(reviewWaiting("changes", FINDINGS, ["Admins exempt: intended?"]));
  assert.equal(card.heading, "Review: changes needed");
  assert.equal(card.summary, "1 high · 1 medium — One shared counter.");
  assert.deepEqual(card.findings.map((item) => item.severity), ["high", "medium"]);
  assert.equal(findingPlace(card.findings[0]), "router.py:96");
  assert.deepEqual(card.questions, ["Admins exempt: intended?"]);
  assert.equal(decisionCard(reviewWaiting("pass")).heading, "Review: ready to ship");
  assert.equal(decisionCard({ kind: "waiting_for_reply" }), null);
});

test("with changes the primary action is another round, with pass it is shipping", () => {
  const waiting = { status: "waiting", actions: ACTIONS };
  assert.equal(decisionPrimary({ actions: ACTIONS, waiting: reviewWaiting("changes", FINDINGS) }).key, "change");
  assert.equal(runNextAction({ ...waiting, waiting: reviewWaiting("changes", FINDINGS) }).key, "change");
  assert.equal(runNextAction({ ...waiting, waiting: reviewWaiting("pass") }).key, "confirm");
  const card = decisionCard(reviewWaiting("changes", FINDINGS));
  assert.equal(decisionLabel(card, ACTIONS[0]), "Ship anyway: push and open the pull request");
  assert.equal(decisionLabel(card, ACTIONS[1]), "Send answers · start another round");
});

test("the fields join into numbered points; nothing typed on changes means fix as proposed", () => {
  const card = decisionCard(reviewWaiting("changes", FINDINGS, ["Admins exempt: intended?", "Log level?"]));
  assert.equal(composeAnswer(card, { findings: {}, questions: {}, other: "" }), "Fix every finding as the reviewer proposes.");
  assert.equal(
    composeAnswer(card, { findings: { 0: "Use the client id header." }, questions: { 1: "warning" }, other: "Keep it small." }),
    "1. Finding src/app/router.py:96 [high]: Use the client id header.\n2. Log level? → warning\n3. Keep it small.",
  );
  assert.equal(answeredCount(card, { findings: {}, questions: { 1: "warning" }, other: "" }), 1);
});

test("readiness lists the agent's questions as fields; no answer means no change text", () => {
  const note = "I read OCX-52.\n\n**Open questions**\n1. Which limit per client: 60 or 100?\n- **Admins exempt?**\n- Plain line.\nWhy not?";
  assert.deepEqual(questionsInNote(note), ["Which limit per client: 60 or 100?", "Admins exempt?"]);
  const card = decisionCard({ kind: "awaiting_confirmation", subject: "readiness", payload: { subject: "readiness", text: note } });
  assert.equal(card.heading, "Is the ticket ready to build?");
  assert.equal(card.questions.length, 2);
  assert.equal(composeAnswer(card, { findings: {}, questions: {}, other: "" }), "");
  assert.equal(decisionPrimary({ actions: ACTIONS, waiting: { kind: "awaiting_confirmation", subject: "readiness", payload: { text: note } } }).key, "confirm");
  assert.equal(decisionLabel(card, ACTIONS[1]), "Send answers, then build");
});

test("on a decision between phases the phases before it show as done", () => {
  const steps = runSteps({
    status: "waiting",
    current_node: { id: "decisions", title: "Decide", kind: "user_confirmation" },
    phase_position: { index: null, total: 3 },
    nodes: [
      { id: "ready", title: "Readiness", kind: "user_confirmation" },
      { id: "build", title: "Build", kind: "phase" },
      { id: "review", title: "Review", kind: "phase" },
      { id: "decisions", title: "Decide", kind: "user_confirmation" },
      { id: "ship", title: "Ship", kind: "phase" },
    ],
  });
  assert.deepEqual(steps.map((step) => step.state), ["done", "done", "pending"]);
});

test("an empty readiness note points to the chat; stop is not a card button", async () => {
  const card = decisionCard({ kind: "awaiting_confirmation", subject: "readiness", payload: { subject: "readiness", text: "" } });
  assert.match(card.summary, /last message in the chat/);
  const { isStopLike, CARD_ACTION_KEYS } = await import("../../src/chat/workflowRun/decisionCardModel.ts");
  assert.equal(isStopLike({ key: "stop", label: "Stop" }), true);
  assert.equal(CARD_ACTION_KEYS.includes("stop"), false);
});

test("each task shows its status: a quiet check for done, labels only where something is going on", async () => {
  const { taskProgress, taskState, taskStatus } = await import("../../src/chat/workflowRun/taskListModel.ts");
  const planned = [{ id: "T1", text: "Count", proof: "tests/a.py::test_a", done: false, status: "open" }];
  assert.equal(taskProgress(planned), "1 task");
  assert.equal(taskState(planned[0], planned).mark, "none");
  const built = [
    { ...planned[0], status: "done", done: true },
    { id: "T2", text: "Header", proof: "tests/a.py::test_b", done: false, status: "changes", note: "T2: send Retry-After" },
    { id: "T3", text: "Log", proof: "tests/a.py::test_c", done: false, status: "in_progress" },
    { id: "T4", text: "Docs", proof: "tests/a.py::test_d", done: true, status: "verified" },
    { id: "T5", text: "Limit", proof: "tests/a.py::test_e", done: false, status: "open" },
  ];
  assert.equal(taskProgress(built), "2/5 done · 1 verified · 1 changes · 1 in progress");
  assert.deepEqual(built.map((item) => taskState(item, built).mark), ["check", "label", "label", "check", "label"]);
  assert.equal(taskState(built[1], built).tone, "problem");
  assert.equal(taskState(built[4], built).label, "Proof test not in the change");
  // A list without statuses: "open" with the proof check in done.
  assert.equal(taskStatus({ ...planned[0], done: true }), "done");
  const legacy = [{ ...planned[0], done: true }, { id: "T2", text: "", proof: "", done: true, status: "open" }];
  assert.equal(taskProgress(legacy), "2/2 done");
  assert.equal(taskState(legacy[0], legacy).label, "Proof test in the change");
  assert.equal(taskStatus({ id: "T9", text: "", proof: "", done: null }), "open");
});

test("a long answer folds to its first lines", async () => {
  const { FOLD_AT, foldPreview } = await import("../../src/chat/workflowRun/workflowRunModel.ts");
  const text = Array.from({ length: 40 }, (_, index) => `line ${index}`).join("\n");
  const preview = foldPreview(text);
  assert.equal(preview.split("\n").length, 12);
  assert.ok(preview.endsWith("…"));
  assert.ok(foldPreview("x".repeat(5000)).length <= FOLD_AT + 1);
});

// Run card mock: steps the platform took on its own are a quiet line in the run's history, never a
// decision card; the review card shows the system tests' screenshots when the run took some.
const HISTORY_NODES = [
  { id: "ready", title: "Readiness", kind: "user_confirmation" },
  { id: "build", title: "Build", kind: "phase" },
  { id: "ship", title: "Decision", kind: "user_confirmation" },
];

function event(id, kind, detail = {}, extra = {}) {
  return { id, kind, node_id: null, detail, actor_id: null, created_at: "2026-11-12T09:24:00Z", ...extra };
}

test("automatic steps show as a grey label with their reason in the run history", async () => {
  const { runHistory, autoRevisedText } = await import("../../src/chat/workflowRun/runHistoryModel.ts");
  const events = [
    event("e1", "run_started"),
    event("e2", "auto_accepted", { reason: "story of epic OCX-1: the product owner answered for the epic" }, { node_id: "ready" }),
    event("e3", "decision", { kind: "confirmation", subject: "readiness", action: "confirmed" }, { node_id: "ready" }),
    event("e4", "node_entered", { kind: "phase", iteration: 1 }, { node_id: "build" }),
    event("e5", "gate_evaluated", { state: "passed" }, { node_id: "build" }),
    event("e6", "review_verdict", { verdict: "changes", findings: 1, attempt: 1 }),
    event("e7", "auto_revised", { revision: 1 }, { node_id: "ship" }),
    event("e8", "node_entered", { kind: "phase", iteration: 2 }, { node_id: "build" }),
    event("e9", "review_verdict", { verdict: "pass", findings: 0, attempt: 1 }),
    event("e10", "decision", { kind: "confirmation", subject: "decisions", action: "confirmed" }, { node_id: "ship", actor_id: "u1" }),
    event("e11", "completed", { outcome: "done" }),
  ];
  const history = runHistory(events, HISTORY_NODES, () => "09:24");
  assert.deepEqual(history.map((entry) => [entry.title, entry.auto, entry.text]), [
    ["Run", null, "started"],
    ["Readiness", "Auto-accepted", "Story of epic OCX-1: the product owner answered for the epic"],
    ["Build", null, "started"],
    ["Review round 1", null, "changes needed · 1 finding"],
    ["Decision", "Auto-revised", "Revision 1: the agent fixes the review's findings on its own"],
    ["Build", null, "started, round 2"],
    ["Review round 2", null, "ready to ship"],
    ["Decision", null, "confirmed"],
    ["Run finished", null, "done"],
  ]);
  assert.ok(history.every((entry) => entry.time === "09:24"));
  // The platform's own decision event (no actor) is not a second line next to its auto_accepted event.
  assert.equal(history.filter((entry) => entry.title === "Readiness").length, 1);
  assert.equal(autoRevisedText(events), "The agent revised once on its own before you were asked");
  assert.equal(autoRevisedText([...events, event("e12", "auto_revised", { revision: 2 })]),
    "The agent revised 2 times on its own before you were asked");
  assert.equal(autoRevisedText([]), "");
  assert.deepEqual(runHistory(null, HISTORY_NODES), []);
  // Unknown node, no reason: still one plain line with a fallback text.
  assert.deepEqual(runHistory([event("x", "auto_accepted", {})], [], () => "")[0],
    { id: "x", time: "", title: "Decision", auto: "Auto-accepted", text: "Everything the platform checks passed" });
});

test("a run that went on with an open high finding says so in the warning tone, counts in words", async () => {
  const { runHistory, openFindingsEventText } = await import("../../src/chat/workflowRun/runHistoryModel.ts");
  const reason = "1 high finding still open after 2 automatic revisions; continued with all 3 open findings on the pull request";
  const [entry] = runHistory([event("o", "accepted_with_open_findings", { reason, high: 1, findings: 3 }, { node_id: "ship" })],
    HISTORY_NODES, () => "");
  assert.equal(entry.auto, "Open findings");
  assert.equal(entry.tone, "attention");
  assert.equal(entry.text, "Continued with 3 open findings (1 high) — decide on the PR");
  assert.equal(entry.note, reason[0].toUpperCase() + reason.slice(1));
  assert.equal(openFindingsEventText({ high: 1, findings: 1 }), "Continued with 1 open finding (1 high) — decide on the PR");
  assert.equal(openFindingsEventText({ high: 2, findings: 2 }), "Continued with 2 open findings (2 high) — decide on the PR");
  assert.equal(openFindingsEventText({}), "Continued with 0 open findings — decide on the PR");
});

test("findings read high first; an unknown severity goes last, never on top", async () => {
  const { readFindings } = await import("../../src/chat/workflowRun/decisionCardModel.ts");
  const read = readFindings([{ severity: "note", file: "a" }, { severity: "Low", file: "b" }, ...FINDINGS, null]);
  assert.deepEqual(read.map((item) => item.severity), ["high", "medium", "low", "note"]);
  assert.deepEqual(readFindings(undefined), []);
});

test("the run's open findings: high first, without a file no place, five shown and the rest behind Show all", async () => {
  const { openFindingsView, findingWhere } = await import("../../src/chat/workflowRun/openFindingsModel.ts");
  const item = (severity, file, line, summary) => ({ severity, file, line, summary, fix: `Fix ${summary}` });
  const list = [item("low", "a.py", 1, "l1"), item("medium", null, null, "m1"), item("high", "src/x/router.py", 96, "h1"),
    item("low", "b.py", 2, "l2"), item("medium", "c.py", null, "m2"), item("low", "d.py", 4, "l3")];
  const folded = openFindingsView(list, false);
  assert.deepEqual(folded.findings.map((f) => f.summary), ["h1", "m1", "m2", "l1", "l2"]);
  assert.equal(folded.more, "Show all 6");
  assert.deepEqual(folded.findings.map(findingWhere), ["router.py:96", "", "c.py", "a.py:1", "b.py:2"]);
  assert.equal(openFindingsView(list, true).findings.length, 6);
  assert.equal(openFindingsView(list.slice(0, 5), false).more, "");
  assert.equal(openFindingsView([], false), null);
  assert.equal(openFindingsView(undefined, false), null);
});

test("an automatic decision never becomes a decision card", () => {
  // auto_accept resolves the node at once: the run no longer waits, so there is no card.
  assert.equal(decisionCard(null), null);
  assert.equal(decisionCard({ kind: "awaiting_review", subject: "decisions" }), null);
});

test("the review card shows up to four screenshots and the rest one click away", async () => {
  const { screensView, runScreenUrl, runScreensPath, SCREENS_PREVIEW } = await import(
    "../../src/chat/workflowRun/decisionCardModel.ts");
  assert.equal(screensView([], false), null);
  assert.equal(screensView(null, false), null);
  const screens = Array.from({ length: 12 }, (_, index) => (
    { name: `screen-${index}.png`, media_type: "image/png", size: 10, node_id: "build" }));
  const folded = screensView(screens, false);
  assert.equal(SCREENS_PREVIEW, 4);
  assert.equal(folded.heading, "What the system tests saw · 12 screenshots");
  assert.equal(folded.shown.length, 4);
  assert.equal(folded.more, "Show all 12");
  const all = screensView(screens, true);
  assert.equal(all.shown.length, 12);
  assert.equal(all.more, null);
  const one = screensView(screens.slice(0, 1), false);
  assert.equal(one.heading, "What the system tests saw · 1 screenshot");
  assert.equal(one.more, null);
  assert.equal(screensView(screens.slice(0, 4), false).more, null);
  assert.equal(runScreensPath("r 1"), "/api/v1/workflow-runs/r%201/screens");
  assert.equal(runScreenUrl("r1", "a b#.png"), "/api/v1/workflow-runs/r1/screens/a%20b%23.png");
});
