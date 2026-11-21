// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/deviceJobFold.test.mjs
//
// A device job's tool steps fold into one line like the chat's ("Used N tools"), the raw
// cards open below it, failures stay visible one line each; the card follows the last message inside the feed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { turnBlocks } from "../../src/chat/devices/deviceTurnView.ts";
import { foldDeviceToolSteps } from "../../src/chat/toolStepFoldModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

test("a step the workspace rules refused is a quiet line with the raw text kept", () => {
  const raw = "PreToolUse:Bash hook error: Octryx policy denied this tool call [rule outside-phase-tools] "
    + "(outside_phase_tools): Phase 'Implement' does not allow this command";
  const fold = foldDeviceToolSteps([tool("u1", "error", raw), tool("u2", "error", "exit code 1")]);
  assert.deepEqual(fold.failures[0], {
    id: "u1", blocked: true, raw,
    text: "Bash blocked by the workspace rules: Phase 'Implement' does not allow this command",
  });
  assert.equal(fold.failures[1].text, "Bash failed: exit code 1");
  assert.equal(fold.failures[1].blocked, undefined);
});

test("a tool the runtime does not offer is one calm sentence without the raw MCP id", () => {
  const raw = "<tool_use_error>Error: No such tool available: mcp__octryx-knowledge__list_workspace_directory</tool_use_error>";
  const fold = foldDeviceToolSteps([tool("u1", "error", raw, "mcp__octryx-knowledge__list_workspace_directory"),
    tool("u2", "error", "exit code 1", "mcp__github__create_issue")]);
  assert.deepEqual(fold.failures[0], { id: "u1", blocked: true, raw, text: "A tool was not available: list workspace directory" });
  assert.equal(fold.failures[1].text, "Create issue failed: exit code 1", "other failures keep their reason, named in words");
});

const tool = (key, status, output = "", name = "Bash") => ({ kind: "tool", key, tool: name, preview: "{\"cmd\":\"ls\"}", status, output });

test("consecutive tool cards become one block between texts", () => {
  const blocks = turnBlocks([{ kind: "text", key: "t1", text: "Looking" }, tool("u1", "done"), tool("u2", "error", "denied"),
    { kind: "text", key: "t2", text: "Done" }, tool("u3", "running")]);
  assert.deepEqual(blocks.map((block) => block.kind === "text" ? block.text : block.tools.length), ["Looking", 2, "Done", 1]);
});

test("the fold line counts tools, says while they run, and lists each failure as one line", () => {
  const done = foldDeviceToolSteps([tool("u1", "done"), tool("u2", "error", "Policy: write outside the folder\nis denied", "Edit")]);
  assert.equal(done.label, "Used 2 tools");
  assert.deepEqual(done.failures, [{ id: "u2", text: "Edit failed: Policy: write outside the folder is denied" }]);
  assert.equal(foldDeviceToolSteps([tool("u1", "running")]).label, "Using tools · 1 so far");
  assert.equal(foldDeviceToolSteps([]), null);
});

function loader(stubs) {
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
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, get window() { return globalThis.window; }, URL, URLSearchParams,
      Intl, console, setTimeout, clearTimeout, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

test("rendered: the job card shows the fold line, not the raw tool JSON, and opens the raw cards below it", async () => {
  globalThis.window = { addEventListener: () => {}, removeEventListener: () => {}, setInterval: () => 1, clearInterval: () => {},
    localStorage: { getItem: () => null, setItem: () => {} }, sessionStorage: { getItem: () => null, setItem: () => {} } };
  const events = [
    { seq: 1, type: "job_accepted", body: { turn_id: "t1" } },
    { seq: 2, type: "job_event", body: { turn_id: "t1", kind: "tool_use", tool: "Bash", tool_use_id: "u1", input_preview: "{\"command\":\"ls -la\"}" } },
    { seq: 3, type: "job_event", body: { turn_id: "t1", kind: "tool_result", tool_use_id: "u1", output: "total 8" } },
    { seq: 4, type: "job_event", body: { turn_id: "t1", kind: "tool_use", tool: "Edit", tool_use_id: "u2", input_preview: "{}" } },
    { seq: 5, type: "job_event", body: { turn_id: "t1", kind: "tool_result", tool_use_id: "u2", is_error: true, output: "Policy denied" } },
  ];
  const api = {
    loadDeviceJobs: async () => ({ items: [{ id: "dj_1", device_id: "dev_a", device_name: "Studio Mac", folder: "/src", profile: "seat",
      status: "running", turn_id: "t1", last_event_seq: 5, events, approvals: [] }] }),
    stopDeviceJob: async () => ({}), decideDeviceApproval: async () => ({}),
  };
  const load = loader({ "/deviceJobsApi": api, "/executionTarget": { hasExecutionTarget: () => true, setExecutionTarget: () => {} } });
  const { DeviceJobPanel } = load("chat/devices/DeviceJobPanel.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(DeviceJobPanel, { sessionId: "s1" })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  const fold = view.root.find((node) => node.props?.["data-testid"] === "tool-fold");
  assert.equal(text(fold.find((node) => node.type === "summary")), "Used 2 tools");
  assert.match(text(fold.find((node) => node.props?.["aria-label"] === "Failed tool steps")), /^Edit failed: Policy denied$/);
  assert.equal(fold.find((node) => node.type === "details").props.open, undefined, "folded by default");
  assert.match(text(fold.find((node) => node.type === "details")), /ls -la/, "the raw cards are inside the fold");
  act(() => view.unmount());
  delete globalThis.window;
});
