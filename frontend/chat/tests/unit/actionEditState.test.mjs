// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionEditState.test.mjs
//
// Editing an Action keeps its server state. The form has no schedule or activation control, so
// an edit sends neither (a paused Action stays paused); a new Action starts active without a schedule.
// Typed admin refusals show their message; the secret-rebind refusal stays special.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useAdminTaskCoreActions } from "../../src/admin/hooks/useAdminTaskCoreActions.ts";
import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";
import { SecretRebindRequiredError } from "../../src/admin/secretRebind/secretRebindModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ---- the real save handler -------------------------------------------------------------------

function saveHarness({ editingTask }) {
  const requests = [];
  const noop = () => {};
  const args = new Proxy(
    {
      readJson: async (url, init) => {
        requests.push({ url, method: init.method, body: JSON.parse(init.body) });
        return { id: editingTask?.id ?? "new-id" };
      },
      editingTask,
      taskFormName: "Nightly sync",
      taskFormDesc: "Keeps tickets in sync",
      taskFormConfig: '{"jira_label": "ops"}',
      taskFormMaxIterations: 32,
      taskFormAgentDefId: "",
      taskRuns: {},
    },
    // Every setter the handler touches is a no-op here; the request body is what is under test.
    { get: (target, key) => (key in target ? target[key] : noop) },
  );
  const { handleSaveTask } = useAdminTaskCoreActions({ args, loadTaskSteps: async () => {} });
  return { requests, save: () => handleSaveTask({ preventDefault() {} }) };
}

test("editing a paused Action sends neither schedule nor activation", async () => {
  const paused = { id: "task-paused", name: "Nightly sync", is_active: false };
  const { requests, save } = saveHarness({ editingTask: paused });
  await save();
  assert.equal(requests.length, 1);
  const [{ url, method, body }] = requests;
  assert.deepEqual([url, method], ["/admin/chat/api/panel/tasks/task-paused", "PUT"]);
  assert.equal("schedule" in body, false);
  assert.equal("is_active" in body, false);
  assert.deepEqual(body, {
    name: "Nightly sync",
    description: "Keeps tickets in sync",
    config: { jira_label: "ops", max_iterations: 32 },
  });
});

test("editing an active Action also leaves its activation to the server", async () => {
  const { requests, save } = saveHarness({ editingTask: { id: "task-active", is_active: true } });
  await save();
  assert.equal("is_active" in requests[0].body, false);
  assert.equal("schedule" in requests[0].body, false);
});

test("creating an Action starts it active without a schedule", async () => {
  const { requests, save } = saveHarness({ editingTask: null });
  await save();
  const [{ url, method, body }] = requests;
  assert.deepEqual([url, method], ["/admin/chat/api/panel/tasks", "POST"]);
  assert.equal(body.is_active, true);
  assert.equal("schedule" in body, false);
});

// ---- typed admin errors ----------------------------------------------------------------------

async function readError(status, payload, statusText = "Unprocessable Entity") {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status,
    statusText,
    json: async () => {
      if (payload === undefined) throw new SyntaxError("not json");
      return payload;
    },
  });
  try {
    await readJson("/admin/chat/api/panel/tasks/x", { method: "PUT", body: "{}" });
  } catch (error) {
    return error;
  } finally {
    globalThis.fetch = original;
  }
  assert.fail("readJson resolved for an error response");
}

test("typed refusals show their message; plain strings and status fallbacks are unchanged", async () => {
  const typed = await readError(422, { detail: { code: "cron_never_fires", message: "This schedule never fires.", field: "schedule" } });
  assert.equal(typed.message, "This schedule never fires.");
  assert.equal((await readError(404, { detail: "Task not found" }, "Not Found")).message, "Task not found");
  assert.equal((await readError(500, undefined, "Internal Server Error")).message, "Internal Server Error");
});

test("malformed details fall back to the status text and are never stringified", async () => {
  for (const detail of [{ code: "x" }, { message: "   " }, { message: 7 }, [{ msg: "field required" }], null]) {
    const error = await readError(422, { detail });
    assert.equal(error.message, "Unprocessable Entity", JSON.stringify(detail));
    assert.doesNotMatch(error.message, /\[object Object\]|code|msg/);
  }
  // A message is text: markup in it stays literal, it is never parsed as HTML.
  const markup = await readError(422, { detail: { message: "<b>bold</b>" } });
  assert.equal(markup.message, "<b>bold</b>");
});

test("the secret-rebind refusal is still its own error, not a typed message", async () => {
  const error = await readError(409, {
    detail: { state: "secret_rebind_required", tool_name: "confluence", changed_target_fields: ["confluence_url"],
      kept_fields: ["confluence_password"], message: "Re-enter the secrets." },
  }, "Conflict");
  assert.ok(error instanceof SecretRebindRequiredError);
  assert.equal(error.refusal.toolName, "confluence");
});

// ---- rendered form notice --------------------------------------------------------------------

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
function loadAdmin(relative) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    if (name.endsWith("/utils/adminPanelHelpers")) return { readJson: () => new Promise(() => {}) };
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
    vm.runInNewContext(output, { module, exports: module.exports, console, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return load(path.join(ADMIN, relative));
}

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

test("the form says what saving does to activation and schedule", () => {
  const { AdminTaskForm } = loadAdmin("components/AdminTaskForm.tsx");
  const noop = () => {};
  const props = (editingTask) => ({
    showTaskForm: true, editingTask, taskFormName: "Nightly", setTaskFormName: noop, taskFormDesc: "",
    setTaskFormDesc: noop, panelAgents: [], taskFormAgentDefId: "", setTaskFormAgentDefId: noop,
    taskFormMaxIterations: 32, setTaskFormMaxIterations: noop, taskFormConfig: "{}", setTaskFormConfig: noop,
    taskFormError: null, taskFormLoading: false, onSaveTask: noop, onCloseTaskForm: noop,
  });
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminTaskForm, props({ id: "t1", name: "Nightly", is_active: false }))); });
  const editing = text(view.root);
  assert.match(editing, /keeps this action's current state \(active or paused\) and any schedule it already has/);
  assert.doesNotMatch(editing, /schedule \*|Schedule \(cron\)/i, "no schedule control is introduced");
  act(() => view.update(createElement(AdminTaskForm, props(null))));
  assert.match(text(view.root), /A new action is created active, without a schedule of its own\./);
  act(() => view.unmount());
});
