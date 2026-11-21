// Render guards for chat pages (Spec Studio design, Work runs, the workflow pill, the coding audit panel): key text and
// structure stay the same when the components are split into smaller parts. Models and heavy children are stubbed by
// module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, icon, load, noop, render, text } from "./renderGuardHarness.mjs";

const byClass = (root, name) => root.findAll((node) => typeof node.type === "string"
  && typeof node.props?.className === "string" && node.props.className.split(" ").includes(name));
const byTestId = (root, id) => root.findAll((node) => typeof node.type === "string" && node.props["data-testid"] === id);

test("Spec Studio design shows directions, colours, deviations, corners, contrast, the stage and the notes", async () => {
  const saved = [];
  const choice = (p) => createElement("div", { "data-testid": "choice", "data-label": p.label }, p.choices.map((c) => c.label).join("|"));
  const { StudioDesign } = load("chat/specStudio/StudioDesign.tsx", {
    ChoiceGroup: { ChoiceGroup: choice },
    ColorRow: { ColorRow: (p) => createElement("span", { "data-testid": "color" }, `${p.label}:${p.value}:${p.source}:${p.locked?.reason ?? "-"}`) },
    corpStudioLocksModel: { lockLabel: (path) => `L:${path}` },
    StatusLabel: { StatusLabel: (p) => createElement("b", null, p.label) },
    MockFrame: { MockFrame: (p) => createElement("div", { "data-testid": "mock", "data-screen": p.screen.id }) },
    specStudioDom: { elementCentre: () => null }, SaveLine: { SaveLine: box("save-line") }, specStudioIcons: { StudioIcon: icon },
    specStudioModel: {
      contrastRows: () => [{ theme: "light", pair: "text/bg", passes: true, ratio: 7.12 }, { theme: "dark", pair: "x", passes: false, ratio: 2 }],
      corporateAssetUrl: (run, path) => `/a/${run}/${path}`,
      directionsOf: () => [{ id: "corporate", name: "Corporate", hint: "Company look" }, { id: "calm", name: "Calm", hint: "Soft" }],
      effectiveDesign: () => ({ direction: "corporate", light: { bg: "#fff", accent: "#00f" }, dark: {}, fonts: { head: "Inter, sans", body: "Roboto, x" } }),
      isContextScreen: (_, id) => id === "s2", mockElements: () => [{ path: "e1", name: "Button" }], RADIUS_MAX: 24,
      screensOf: (p) => p.screens, validRadius: (v) => (/^\d+$/.test(v) ? Number(v) : null),
      valueMark: (_, __, path) => ({ locked: path === "light.bg", source: path === "light.bg" ? "ci" : "derived" }),
    },
  });
  const payload = {
    artefact: { target: "web", nav: [], title: "App" }, run_id: "r1", frozen: false, base: { nav: ["Home"] },
    state: { comments: [{ id: "c1", screen: "s1", device: "phone", element: "Button", text: "Bigger" }] }, design: { radius: 8 },
    corporate: { profile_name: "ACME", locks: [], logo: "logo.svg", icons: {} },
    deviations: [{ path: "light.accent", chosen: "#00f", corporate: "#f00", reason: "brand" }],
    screens: [{ id: "s1", name: "Home", note: "", next_step: "Pay" }, { id: "s2", name: "List", note: "Old" }],
  };
  const studio = { save: async (area, change) => { saved.push([area, change.op]); return null; }, saves: { design: {}, comments: {} }, markDirty: noop };
  const view = await render(StudioDesign, { payload, studio });
  const root = view.root;
  assert.deepEqual(byClass(root, "studio-label").map(text), ["Style direction", "Colours (light theme)", "Fonts",
    "Differs from Corporate: ACME", "Corners", "Contrast (WCAG AA, 4.5 : 1)", "Add a note to an element"]);
  assert.deepEqual(root.findAll((n) => n.props["data-testid"] === "choice" && typeof n.type === "string").map(text),
    ["Corporate|Calm", "Home|List (existing)", "Desktop|Phone", "Light|Dark", "With data|Empty"]);
  assert.deepEqual(byTestId(root, "color").map(text), ["Background:#fff:Corporate:Locked by the Corporate Identity ACME", "Main action:#00f:derived:-"]);
  assert.equal(text(byClass(root, "studio-deviation__diff")[0]), "L:light.accent: #00f instead of #f00");
  assert.equal(text(byClass(root, "studio-contrast")[0]), "Passestext/bg: 7.1 : 1");
  assert.deepEqual(root.findAll((n) => n.type === "button").map(text), ["100 %", "Comment", ""]);
  assert.equal(byTestId(root, "mock")[0].props["data-screen"], "s1");
  assert.equal(text(byClass(root, "studio-comment")[0]), "1Home · Phone · at “Button”");
  assert.equal(byTestId(root, "save-line").length, 2);
  assert.match(text(root), /Inter for headings, Roboto for text\./);
  assert.match(text(root), /Next step: Pay/);
  await act(async () => root.findByProps({ "aria-pressed": false, disabled: false }).props.onClick());
  assert.equal(byClass(root, "studio-banner").length, 1);
  await act(async () => root.findByProps({ "aria-label": "Corner radius in px" }).props.onChange({ target: { value: "12" } }));
  await act(async () => root.findByProps({ "aria-label": "Corner radius in px" }).props.onBlur());
  assert.deepEqual(saved, [["design", "design"]]);
  act(() => view.unmount());
});

test("Work runs lists what waits, every run with step, result and cost, and the totals", async () => {
  const runs = [
    { id: "r1", title: "Fix login", status: "waiting", workflow_key: "bug-fix", session_id: "s1", cost: 1.5, step: { title: "Review" } },
    { id: "r2", title: "Docs", status: "completed", workflow_key: "docs", workflow_title: "Docs writer", cost: 0.25,
      pull_request: { url: "https://x/pr/7", id: 7 }, created_at: "2026-01-01" },
  ];
  const { WorkRunsPage } = load("chat/work/WorkRunsPage.tsx", {
    chatApiClient: { readJson: async () => ({ runs }) }, TimeText: { TimeText: (p) => createElement("time", null, p.value ?? p.fallback) },
    LoadingState: { LoadingState: box("loading") }, StatusLabel: { StatusLabel: (p) => createElement("b", { "data-tone": p.tone }, p.label) },
    RunTokens: { RunTokensPanel: (p) => createElement("div", { "data-testid": "tokens" }, p.title) },
    SeatCell: { SeatCell: (p) => createElement("span", null, p.empty) },
  });
  const view = await render(WorkRunsPage, { projectId: "p1" });
  const root = view.root;
  assert.equal(text(root.findByType("h2")), "Waiting for you · 1");
  assert.equal(text(byTestId(root, "work-runs-waiting")[0]), "Fix loginReview · WaitingNeeds youAPI $1.50Open decision");
  assert.deepEqual(root.findAll((n) => n.type === "th").map(text).slice(0, 5), ["Run", "Workflow", "Step", "Result", "API cost"]);
  const rows = root.findAll((n) => n.type === "tr").slice(1);
  assert.deepEqual(rows.map((row) => row.findAll((n) => n.type === "td").map(text)), [
    ["Fix login", "Bug fix", "Needs youReview", "–", "$1.50", "–", "–", "Tokens"],
    ["Docs", "Docs writer", "Shipped", "PR #7", "$0.25", "–", "2026-01-01", "Tokens"],
  ]);
  assert.equal(text(byTestId(root, "work-runs-total")[0]), "API cost of these 2 runs: $1.75.");
  await act(async () => byTestId(root, "work-runs-tokens")[1].props.onClick());
  assert.equal(text(byTestId(root, "tokens")[0]), "Docs");
  act(() => view.unmount());
});

test("the workflow pill names the choice, its class and steps, and lists every workflow", async () => {
  const { ModeOfWorkPill } = load("chat/composer/ModeOfWorkPill.tsx", {
    ChatShellIcons: { WorkflowIcon: () => createElement("i") },
  });
  const chosen = [];
  const options = [{ key: "fix", title: "Fix", capability_class: "change", steps: [{ label: "Edit", mode: "strict" }] },
    { key: "none", title: "Chat only", selection: "no_workflow" }];
  const props = { composerDisabled: false, workflowOptions: options, selectedWorkflowKey: "fix", setSelectedWorkflowKey: (k) => chosen.push(k),
    workflowPillLabel: "", selectedWorkflowCapability: null };
  const view = await render(ModeOfWorkPill, props);
  const root = view.root;
  const label = root.findByType("label");
  assert.equal(label.props.className, "composer-pill composer-pill--workflow composer-pill--explicit");
  assert.equal(label.props.title, "Workflow for the next message: Fix\nSteps: 1 Edit (strict)");
  assert.equal(text(byClass(root, "composer-pill__display")[0]), "WorkflowFixChange· 1 steps");
  assert.deepEqual(root.findAll((n) => n.type === "option").map(text), ["Automatic", "Fix · Change", "Chat only"]);
  act(() => root.findByType("select").props.onChange({ target: { value: root.findAll((n) => n.type === "option")[2].props.value } }));
  assert.deepEqual(chosen, ["none"]);
  await act(async () => view.update(createElement(ModeOfWorkPill, { ...props, selectedWorkflowKey: "gone", workflowPillLabel: "x" })));
  assert.deepEqual(root.findAll((n) => n.type === "option").map(text), ["Automatic", "gone · unavailable in this Workspace", "Fix · Change", "Chat only"]);
  await act(async () => view.update(createElement(ModeOfWorkPill, { ...props, selectedWorkflowKey: "", workflowPillLabel: "" })));
  assert.equal(root.findByType("label").props.className, "composer-pill composer-pill--workflow");
  assert.equal(root.findByType("label").props.title, "Workflow for the next message: Automatic");
  assert.equal(text(byClass(root, "composer-pill__display")[0]), "WorkflowAutomatic");
  assert.equal(root.findByType("select").props.value, "");
  act(() => view.unmount());
});

test("the coding audit panel shows the empty state, then gates, PR summary and timeline", async () => {
  const report = {
    quality_summary: { status: "blocked", blocking: 1, total: 2 }, source_key: "src-1",
    quality_gates: [{ key: "g1", label: "Tests", status: "failed", reason: "red", blocking: true }, { key: "g2", label: "Lint", status: "ok", reason: "fine" }],
    pr_summary: { ready_to_open_pr: false, title: "PR", request: "Do it", repositories: ["r"], branches: [], files: ["a", "b"], reviewers: [],
      risks: [{ label: "Auth", reason: "touches login" }] },
    timeline: [{ id: "e1", title: "Started", kind: "run", status: "", created_at: "" }, { id: "e2", title: "Done", kind: "gate", status: "ok", created_at: "t", summary: "S" }],
    evidence: { review_event_count: 2 },
  };
  const { CodingAuditPanel } = load("chat/coding/CodingAuditPanel.tsx", { workCodingApi: { evaluateCodingQualityGates: async () => report } });
  const view = await render(CodingAuditPanel, { session: { id: "cs1" }, report: null, fallbackBlocked: true });
  const root = view.root;
  assert.equal(text(root.findByType("h3")), "No audit report captured yet.");
  assert.equal(byClass(root, "coding-detail__warning").length, 1);
  await act(async () => root.findByType("button").props.onClick());
  assert.equal(text(root.findAllByType("h3")[0]), "blocked");
  assert.equal(byClass(root, "coding-audit__hero")[0].props.className, "coding-audit__hero is-blocked");
  assert.deepEqual(byClass(root, "coding-audit-metric").map(text), ["Blocking1", "Timeline2", "Reviews2", "Pipeline stages0"]);
  assert.deepEqual(byClass(root, "coding-review__section-heading").map(text),
    ["Gate evidence1 blocking", "Reviewer PR summarynot ready", "Audit timelinesrc-1"]);
  assert.deepEqual(byClass(root, "coding-audit-gate").map(text), ["Testsfailedred", "Lintokfine"]);
  assert.deepEqual(byClass(root, "coding-audit-list").map(text), ["Repositoriesr", "BranchesNot captured", "Filesa, b",
    "ReviewersNot captured", "RisksAuth: touches login"]);
  assert.deepEqual(root.findAll((n) => n.type === "li").map(text), ["Startedrun · recorded · no timestamp", "Donegate · ok · tS"]);
  act(() => view.unmount());
});
