import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { workspaceKnowledgeApi } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared TS hook handles pure modules. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { KnowledgeSourceUploadPanel } = await import("../../src/chat/knowledge/KnowledgeSourceUploadPanel.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

function mount() {
  const originalDocument = globalThis.document; const originalWindow = globalThis.window;
  let restored = 0; let focused = 0; let closed = 0; let uploaded = 0; const prompts = [];
  const document = new EventTarget(); document.activeElement = { focus: () => restored++ };
  globalThis.document = document; globalThis.window = { confirm: (message) => { prompts.push(message); return false; } };
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(KnowledgeSourceUploadPanel, {
    workspaceId: "workspace-a", onClose: () => closed++, onUploaded: () => uploaded++,
  }), { createNodeMock: (node) => node.props.role === "dialog" ? { contains: () => false, focus: () => focused++ } : null }); });
  return { renderer, prompts, get restored() { return restored; }, get focused() { return focused; },
    get closed() { return closed; }, get uploaded() { return uploaded; },
    form: () => renderer.root.findByType("form"),
    escape: () => act(() => { const event = new Event("keydown", { cancelable: true }); Object.defineProperty(event, "key", { value: "Escape" }); document.dispatchEvent(event); }),
    selectFile: () => act(() => {
      renderer.root.findAllByType("input").find((node) => node.props.type === "file").props.onChange({ target: { files: [new File(["example"], "guide.txt", { type: "text/plain" })] } });
      renderer.root.findByType("form").props.onChange();
    }),
    unmount: () => { act(() => renderer.unmount()); globalThis.document = originalDocument; globalThis.window = originalWindow; } };
}

test("Add document uses the shared side panel with linked footer action and focus restoration", () => {
  const panel = mount();
  try {
    const dialog = panel.renderer.root.find((node) => node.props.role === "dialog");
    assert.equal(dialog.props["aria-modal"], "true");
    assert.match(dialog.props.className, /\bds-panel\b/);
    const labels = panel.renderer.root.findAllByType("button").map((node) => [].concat(node.props.children).join(""));
    assert.ok(labels.includes("Cancel") && !labels.includes("Close"), "Cancel, not Close");
    assert.equal(panel.focused, 1);
    const submit = panel.renderer.root.findAllByType("button").find((node) => node.props.type === "submit");
    assert.equal(submit.props.form, panel.form().props.id);
    assert.equal(submit.props.disabled, true);
    panel.escape();
    assert.equal(panel.closed, 1);
  } finally { panel.unmount(); }
  assert.equal(panel.restored, 1);
});

test("Escape and backdrop preserve a dirty upload until discard is confirmed", () => {
  const panel = mount();
  try {
    panel.selectFile(); panel.escape();
    assert.equal(panel.closed, 0);
    assert.equal(panel.prompts.length, 1);
    globalThis.window.confirm = () => true;
    const backdrop = panel.renderer.root.findByProps({ className: "ds-panel__backdrop" });
    act(() => backdrop.props.onMouseDown({ target: 1, currentTarget: 2 }));
    assert.equal(panel.closed, 0, "clicks inside the drawer do not dismiss it");
    act(() => backdrop.props.onMouseDown({ target: 1, currentTarget: 1 }));
    assert.equal(panel.closed, 1);
  } finally { panel.unmount(); }
});

test("upload keeps the existing workspace API and success result; an in-flight upload cannot be dismissed", async () => {
  const originalUpload = workspaceKnowledgeApi.upload; let finish; const calls = [];
  workspaceKnowledgeApi.upload = (workspace, body) => { calls.push({ workspace, body }); return new Promise((resolve) => { finish = resolve; }); };
  const panel = mount();
  try {
    panel.selectFile();
    act(() => panel.form().props.onSubmit({ preventDefault() {} }));
    assert.equal(calls[0].workspace, "workspace-a");
    assert.equal(calls[0].body.get("display_title"), "guide.txt");
    assert.equal(calls[0].body.get("file").name, "guide.txt");
    assert.equal(panel.renderer.root.findByType("fieldset").props.disabled, true);
    panel.escape(); assert.equal(panel.closed, 0);
    await act(async () => finish({ revision_ordinal: 2, projection: "parsing", created: true }));
    assert.equal(panel.uploaded, 1);
    assert.match(JSON.stringify(panel.renderer.toJSON()), /uploaded/);
    panel.escape(); assert.equal(panel.closed, 1);
    assert.equal(panel.prompts.length, 0, "successful upload clears unsaved state");
  } finally { panel.unmount(); workspaceKnowledgeApi.upload = originalUpload; }
});
