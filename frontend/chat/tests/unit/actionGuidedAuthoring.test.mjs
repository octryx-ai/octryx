// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionGuidedAuthoring.test.mjs
//
// Guided "Run an agent" Action authoring, rendered with the real header, form,
// useAdminTaskState and useAdminTaskCoreActions; readJson is the only stub and the agent's
// execution lookups stay pending until the test answers them.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const MODES = [
  { id: "1", key: "diagnosis", name: "Diagnosis", is_active: true },
  { id: "2", key: "change", name: "Change", is_active: true },
  { id: "3", key: "retired", name: "Retired", is_active: false },
];
const WORKSPACES = [{ id: "ws-1", name: "Alpha" }, { id: "ws-2", name: "Beta" }];
const agent = (id, overrides = {}) => ({
  id, name: `Agent ${id}`, isActive: true, projectId: "", agentType: "diagnosis", goal: `Goal of ${id}`,
  systemPrompt: "", outputPrompt: "", steps: [], ...overrides,
});
const AGENTS = [
  agent("global"),
  agent("catalog-global", { projectId: null }), // the agent catalog's explicit global value
  agent("no-workspace-field", { projectId: undefined }), // missing metadata is not global
  agent("odd-workspace-field", { projectId: 7 }),
  agent("beta-only", { projectId: "ws-2", agentType: "change" }),
  agent("alpha-only", { projectId: "ws-1" }),
  agent("inactive", { isActive: false }),
  agent("silent", { goal: "" }), // no authored instruction of its own
  agent("retired-mode", { agentType: "retired" }),
];

let requests = [];
let modesReply = () => Promise.resolve(MODES);
function stubRead(url, init = {}) {
  const method = init.method || "GET";
  const body = init.body ? JSON.parse(init.body) : null;
  if (url.endsWith("/panel/modes")) return modesReply();
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, method, body, ...settle });
  if (method !== "GET") settle.resolve({ id: "saved", ...body });
  return promise;
}

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
    vm.runInNewContext(output, {
      module, exports: module.exports, console, setTimeout, clearTimeout, AbortController, URL, URLSearchParams,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(ADMIN, relative));
}

const loadModule = makeLoader({ "/utils/adminPanelHelpers": { readJson: stubRead } });
const { AdminNavigationContext } = loadModule("adminNavigation.ts");
const { AdminTasksTabHeader } = loadModule("components/AdminTasksTabHeader.tsx");
const { AdminTaskForm } = loadModule("components/AdminTaskForm.tsx");
const { useAdminTaskState } = loadModule("hooks/useAdminTaskState.ts");
const { useAdminTaskCoreActions } = loadModule("hooks/useAdminTaskCoreActions.ts");

let mounted = null;
function mount({ workspaces = WORKSPACES, agents = AGENTS } = {}) {
  if (mounted) act(() => mounted.unmount());
  requests = [];
  const handle = { opened: [] };
  function Harness() {
    const state = useAdminTaskState();
    const actions = useAdminTaskCoreActions({ args: { ...state, readJson: stubRead }, loadTaskSteps: async () => {} });
    Object.assign(handle, { state, actions });
    const ctx = { ...state, onOpenTaskForm: actions.handleOpenTaskForm, onCloseTaskForm: actions.closeTaskForm };
    return createElement("div", null,
      createElement(AdminTasksTabHeader, { ctx }),
      createElement(AdminTaskForm, {
        ...state, panelAgents: agents, projects: workspaces,
        onSaveTask: actions.handleSaveTask, onCloseTaskForm: actions.closeTaskForm,
      }));
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider,
      { value: { openAdminTab: (tab) => handle.opened.push(tab) } }, createElement(Harness)));
  });
  mounted = view;
  const byId = (id) => view.root.findAll((node) => typeof node.type === "string" && node.props.id === id)[0] ?? null;
  const testId = (id) => view.root.findAll((node) => node.props["data-testid"] === id).map(text)[0] ?? null;
  const ui = {
    handle, view, byId, testId,
    openNew: () => act(() => view.root.find((node) => node.type === "button" && node.props["data-testid"] === "action-new").props.onClick()),
    edit: (task) => act(() => handle.actions.handleOpenTaskForm(task)),
    change: (id, value) => act(() => byId(id).props.onChange({ target: { value } })),
    agentOptions: () => byId("action-guided-agent").findAllByType("option").map((option) => option.props.value).filter(Boolean),
    submitDisabled: () => view.root.find((node) => node.type === "button" && node.props.type === "submit").props.disabled,
    blocker: () => testId("action-guided-blocker"),
    lookups: () => requests.filter((request) => request.url.endsWith("/designer-document")),
    writes: () => requests.filter((request) => request.method !== "GET"),
    answer: (request, value) => act(async () => { request.resolve(value); }),
    submit: () => act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); }),
    capability: (value) => act(() => view.root.find((node) => node.type === "input" && node.props.value === value).props.onChange()),
    buttons: (label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label),
  };
  return ui;
}
const published = (number, latest = number) => ({ execution: { mode: "published", published_revision_number: number }, revision: { revision_number: latest } });
const DRAFT = { execution: { mode: "draft", published_revision_number: null }, revision: null };
// The designer document's newest revision, here exactly the published one, with its snapshot.
const publishedWithSnapshot = (number, definition, steps = []) => ({
  execution: { mode: "published", published_revision_number: number },
  revision: { revision_number: number, status: "published", snapshot: { definition, steps } },
});

test("a new Action requires an explicit workspace and agent; only active global or same-workspace agents are offered", async () => {
  const ui = mount();
  ui.openNew();
  await act(async () => {}); // the permission-mode catalog answers
  assert.equal(ui.byId("action-guided-workspace").props.value, "", "no preselected workspace");
  assert.equal(ui.byId("action-guided-agent").props.disabled, true);
  assert.equal(ui.byId("task-form-type"), null, "no type choice for a new Action");
  assert.equal(ui.submitDisabled(), true);
  assert.equal(ui.blocker(), "Choose the workspace this action runs in.");

  ui.change("action-guided-workspace", "ws-2");
  assert.deepEqual(ui.agentOptions(), ["global", "catalog-global", "beta-only", "silent", "retired-mode"],
    "inactive, other-workspace and workspace-less (missing or invalid) agents are not offered");
  assert.equal(ui.blocker(), "Choose the agent this action runs.");

  ui.change("action-guided-agent", "beta-only");
  assert.equal(ui.lookups().length, 1);
  assert.equal(ui.blocker(), "Checking which version of the agent this action runs…");
  assert.equal(ui.submitDisabled(), true);
  await ui.answer(ui.lookups()[0], published(3, 4));
  assert.equal(ui.testId("action-guided-execution"),
    "Each run uses published revision 3 of the agent. The agent has newer changes; they are used only after they are published.");
  assert.ok(ui.testId("action-guided-mode").startsWith("Run mode: Change, taken from the agent."));
  const link = ui.view.root.find((node) => node.type === "a" && text(node) === "Open agent ↗");
  assert.equal(link.props.href, "/chat?area=workflows&tab=agents&agent_id=beta-only", "the canonical agent page");
  assert.equal(ui.submitDisabled(), false);

  act(() => ui.handle.state.setTaskFormName("Beta digest"));
  await ui.submit();
  const [post] = ui.writes();
  assert.deepEqual([post.method, post.url], ["POST", "/admin/chat/api/panel/tasks"]);
  assert.deepEqual(post.body, {
    name: "Beta digest", description: "", task_type: "agent_run", agent_type: "change",
    config: { max_iterations: 32, agent_definition_id: "beta-only" },
    project_id: "ws-2", is_active: true,
    dispatch_binding: "agent_definition", // A new guided Action states its binding explicitly
  });
});

test("changing the workspace clears an agent that cannot run there", () => {
  const ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "alpha-only");
  ui.change("action-guided-workspace", "ws-2");
  assert.equal(ui.handle.state.taskFormAgentDefId, "");
  ui.change("action-guided-agent", "global");
  ui.change("action-guided-workspace", "ws-1");
  assert.equal(ui.handle.state.taskFormAgentDefId, "global", "a global agent stays");
});

test("unknown, unpublished, misconfigured or failed execution lookups block saving", async () => {
  const ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "global");
  const cases = [
    [published(null), "The agent has no published revision, so its runs would be refused. Publish it on the agent's page first."],
    [{ execution: { mode: "nonsense", published_revision_number: null } }, "The platform's agent execution mode is not configured correctly, so this agent's runs would be refused."],
    [{ revision: null }, "This server did not say which version of the agent runs, so the action cannot be saved here."],
  ];
  for (const [reply, message] of cases) {
    await ui.answer(ui.lookups().at(-1), reply);
    assert.equal(ui.testId("action-guided-execution").replace(/ ?Retry$/, ""), message);
    assert.equal(ui.submitDisabled(), true);
    act(() => ui.handle.state.setTaskFormAgentDefId("alpha-only"));
    act(() => ui.handle.state.setTaskFormAgentDefId("global"));
  }
  await act(async () => { ui.lookups().at(-1).reject(new Error("Service Unavailable")); });
  assert.equal(ui.blocker(), "Could not check which version of the agent runs: Service Unavailable");
  const before = ui.lookups().length;
  act(() => ui.buttons("Retry")[0].props.onClick());
  assert.equal(ui.lookups().length, before + 1, "Retry asks again");
  await ui.answer(ui.lookups().at(-1), { execution: { mode: "draft", published_revision_number: null } });
  assert.equal(ui.testId("action-guided-execution"),
    "Each run uses the agent's saved settings and steps as they are at that time, including unpublished changes.");
  assert.equal(ui.submitDisabled(), false);
  await ui.submit();
  assert.equal(ui.writes().length, 1);
});

test("a slow lookup for a previously chosen agent never stands in for the current one", async () => {
  const ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-2");
  ui.change("action-guided-agent", "global");
  ui.change("action-guided-agent", "beta-only");
  const [first, second] = ui.lookups();
  await ui.answer(second, published(null));
  await ui.answer(first, published(7));
  assert.equal(ui.handle.state.taskFormAgentDefId, "beta-only");
  assert.ok(ui.testId("action-guided-execution").startsWith("The agent has no published revision"));
  assert.equal(ui.submitDisabled(), true);
});

test("an agent without instructions needs one for each run; an inactive agent mode blocks", async () => {
  const ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "silent");
  await ui.answer(ui.lookups()[0], DRAFT); // draft execution runs the live row, which has no instruction
  assert.ok(ui.blocker().startsWith("This agent has no instructions of its own"));
  ui.change("action-guided-prompt", "Summarise yesterday's failures.");
  assert.equal(ui.submitDisabled(), false);
  assert.deepEqual(JSON.parse(ui.handle.state.taskFormConfig), { prompt: "Summarise yesterday's failures." });

  ui.change("action-guided-agent", "retired-mode");
  await ui.answer(ui.lookups().at(-1), DRAFT);
  assert.equal(ui.blocker(), 'The agent\'s run mode "retired" no longer exists, so the action cannot be saved. Change it on the agent\'s page.');
});

const GUIDED_ROW = {
  id: "task-guided", name: "Nightly digest", description: "", task_type: "agent_run", agent_type: "diagnosis",
  schedule: "0 9 * * mon", is_active: false, step_count: 0, project_id: "ws-1",
  config: {
    agent_definition_id: "global", max_iterations: 12, prompt: "Old instruction", capability_class: "change",
    custom_key: { nested: [1, 2, { deep: null }] }, flag: true,
  },
};

test("editing keeps unknown config exactly, the workspace and the paused schedule", async () => {
  const ui = mount();
  ui.edit(GUIDED_ROW);
  assert.equal(ui.byId("action-guided-workspace").children.map(text).join("").startsWith("Alpha"), true, "read-only workspace");
  assert.equal(ui.view.root.find((node) => node.type === "input" && node.props.value === "change").props.checked, true);
  await ui.answer(ui.lookups()[0], published(2));
  ui.change("action-guided-prompt", "New instruction");
  await ui.submit();
  const [put] = ui.writes();
  assert.deepEqual([put.method, put.url], ["PUT", "/admin/chat/api/panel/tasks/task-guided"]);
  assert.deepEqual(put.body.config, {
    prompt: "New instruction", capability_class: "change", custom_key: { nested: [1, 2, { deep: null }] }, flag: true,
    max_iterations: 12, agent_definition_id: "global",
  });
  assert.deepEqual(["schedule" in put.body, "is_active" in put.body, "project_id" in put.body], [false, false, false]);
  assert.equal(put.body.task_type, "agent_run");
});

test("invalid JSON or reserved keys typed into it are refused, never erased or retyped", async () => {
  const ui = mount();
  ui.edit(GUIDED_ROW);
  await ui.answer(ui.lookups()[0], published(2));
  ui.change("task-form-config", '{"agent_definition_id": "other", "flag": true}');
  assert.equal(ui.blocker(), 'Remove "agent_definition_id" from Config (JSON).');
  // The handler refuses too, also when called without the form's gate (the advanced path).
  await act(async () => { await ui.handle.actions.handleSaveTask({ preventDefault() {} }); });
  assert.equal(ui.handle.state.taskFormError, 'Remove "agent_definition_id" from Config (JSON); set it with the form\'s own field.');
  assert.equal(ui.writes().length, 0);
  assert.equal(ui.handle.state.taskFormConfig, '{"agent_definition_id": "other", "flag": true}', "the typed text is untouched");

  ui.change("task-form-config", "{ not json");
  assert.equal(ui.byId("action-guided-prompt").props.disabled, true, "guided fields wait for valid JSON");
  await ui.submit();
  assert.equal(ui.handle.state.taskFormError, "Config is not valid JSON. Fix it under Advanced.");
  assert.equal(ui.writes().length, 0);

  ui.change("task-form-config", '{"capability_class": "admin"}');
  await ui.submit();
  assert.ok(ui.handle.state.taskFormError.startsWith('The saved capability_class "admin" is not one of'));
  assert.equal(ui.writes().length, 0);
  ui.capability("read_only");
  assert.deepEqual(JSON.parse(ui.handle.state.taskFormConfig), { capability_class: "read_only" });
});

test("Actions the guided form cannot represent show the reason and offer no type, run mode or agent choice", () => {
  const ui = mount();
  const cases = [
    [{ ...GUIDED_ROW, step_count: 2 }, "This action has steps. Its enabled steps run instead of a single agent turn, so it is edited here."],
    [{ ...GUIDED_ROW, task_type: "jira_watch" }, 'This action has the type "jira_watch", which the guided form does not edit.'],
    [{ ...GUIDED_ROW, config: { prompt: "x" } }, "This action names no agent, so the guided form does not edit it."],
    [{ ...GUIDED_ROW, project_id: undefined }, "The action's Workspace is not known, so it is edited here."],
  ];
  for (const [row, reason] of cases) {
    ui.edit(row);
    assert.equal(text(ui.view.root.find((node) => node.props.className === "action-guided__unguided task-form__field--full")), reason);
    assert.equal(ui.byId("task-form-type"), null, "no type choice");
    assert.equal(ui.byId("action-guided-agent"), null, "no guided fields");
  }
});

test("Cancel → New starts clean; empty workspace, agent and catalog states guide instead of preselecting", async () => {
  let ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-2");
  ui.change("action-guided-agent", "beta-only");
  ui.openNew(); // the header button reads Cancel while a new form is open
  ui.openNew();
  assert.deepEqual([ui.handle.state.taskFormProjectId, ui.handle.state.taskFormAgentDefId], ["", ""]);

  ui = mount({ workspaces: [] });
  ui.openNew();
  act(() => ui.buttons("Open workspaces")[0].props.onClick());
  assert.deepEqual(ui.handle.opened, ["projects"]);

  ui = mount({ agents: [agent("inactive", { isActive: false })] });
  ui.openNew();
  ui.change("action-guided-workspace", "ws-1");
  act(() => ui.buttons("Open agents")[0].props.onClick());
  assert.deepEqual(ui.handle.opened, ["agents"], "the canonical agent home, not a form here");

  modesReply = () => Promise.reject(new Error("503"));
  ui = mount();
  ui.openNew();
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "global");
  await ui.answer(ui.lookups()[0], published(1));
  assert.equal(ui.blocker(), "Run modes could not be loaded: 503");
  modesReply = () => Promise.resolve(MODES);
});

test("published execution is checked against the published content, never the live draft", async () => {
  const ui = mount();
  ui.openNew();
  await act(async () => {});
  ui.change("action-guided-workspace", "ws-1");

  // Live draft cleared (no goal), published revision 4 still authored: allowed, no deferral note.
  ui.change("action-guided-agent", "silent");
  await ui.answer(ui.lookups().at(-1), publishedWithSnapshot(4, { goal: "Report failed deploys", system_prompt: "" }));
  assert.equal(ui.blocker(), null);
  assert.equal(ui.submitDisabled(), false);
  assert.equal(ui.testId("action-guided-instruction-note"), null);

  // Live row authored, published revision 5 has nothing of its own: blocked on the published content.
  ui.change("action-guided-agent", "global");
  await ui.answer(ui.lookups().at(-1), publishedWithSnapshot(5, { goal: "", system_prompt: " " }, [
    { instructions: "Only a disabled step", is_enabled: false },
  ]));
  assert.ok(ui.blocker().startsWith("The published revision of this agent has no instructions of its own"));
  ui.change("action-guided-prompt", "Report failed deploys");
  assert.equal(ui.submitDisabled(), false, "an instruction for each run is enough");
  ui.change("action-guided-prompt", "");

  // Published revision 3 with a newer draft: no trustworthy published payload here, so the check is
  // the runtime's, stated as such, and the live row decides nothing.
  ui.change("action-guided-agent", "silent");
  await ui.answer(ui.lookups().at(-1), published(3, 4));
  assert.equal(ui.blocker(), null);
  assert.equal(ui.testId("action-guided-instruction-note"),
    "Whether published revision 3 gives the agent a task is checked when the action runs. If it has no instructions of its own and this field is empty, the run is refused.");
  // The newest revision being a draft with the same number is not the published content either.
  ui.change("action-guided-agent", "global");
  await ui.answer(ui.lookups().at(-1), { execution: { mode: "published", published_revision_number: 6 },
    revision: { revision_number: 6, status: "draft", snapshot: { definition: { goal: "" } } } });
  assert.ok(ui.testId("action-guided-instruction-note").startsWith("Whether published revision 6"));
  assert.equal(ui.submitDisabled(), false);
});

test("a published revision must be a positive integer; anything else is not runnable", async () => {
  const ui = mount();
  ui.openNew();
  await act(async () => {});
  ui.change("action-guided-workspace", "ws-1");
  ui.change("action-guided-agent", "global");
  for (const value of [0, -2, 1.5, "3", Number.NaN, {}]) {
    await ui.answer(ui.lookups().at(-1), { execution: { mode: "published", published_revision_number: value } });
    assert.equal(ui.testId("action-guided-execution").replace(/ ?Retry$/, ""),
      "This server reported an invalid published revision, so the action cannot be saved here.", String(value));
    assert.equal(ui.submitDisabled(), true, String(value));
    act(() => ui.buttons("Retry")[0].props.onClick());
  }
  await ui.answer(ui.lookups().at(-1), { execution: { mode: "published" } });
  assert.ok(ui.testId("action-guided-execution").startsWith("The agent has no published revision"));
  assert.equal(ui.submitDisabled(), true);
});

test("a workspace explicitly marked inactive is never offered", () => {
  const ui = mount({ workspaces: [...WORKSPACES, { id: "ws-old", name: "Old", is_active: false }] });
  ui.openNew();
  const offered = ui.byId("action-guided-workspace").findAllByType("option").map((option) => option.props.value);
  assert.deepEqual(offered, ["", "ws-1", "ws-2"]);
});
