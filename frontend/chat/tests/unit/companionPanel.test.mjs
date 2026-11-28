// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionPanel.test.mjs
//
// Octryx companion, stage 1, rendered: the button names what needs the person, the side panel answers a
// question by choice and by free text through the item's own request, shows a refusal in the server's words on the
// item, removes the item on success, shows a device approval's countdown, reports a failed attention read without
// asking any other list, and keeps the logo still under reduced motion. Requests are stubs.
process.env.TZ = "Europe/Zurich";

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

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const tick = (ms = 0) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

function loader(extra) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setInterval, clearInterval, setTimeout, clearTimeout, CustomEvent, Set, Map, String, Array, Boolean, RegExp,
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
  return (relative) => loadFile(path.join(SRC, relative));
}

function windowStub({ reducedMotion = false } = {}) {
  const target = new EventTarget();
  const storage = new Map();
  return {
    location: { origin: "http://localhost", protocol: "http:", host: "localhost", search: "", href: "http://localhost/chat" },
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)) },
    matchMedia: (query) => ({ matches: reducedMotion && query.includes("reduce"), addEventListener() {}, removeEventListener() {} }),
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    dispatchEvent: (event) => target.dispatchEvent(event),
  };
}

const ANSWER = "/api/v1/clarifications/q1/answer";
const QUESTION = {
  key: "question:q1", kind: "question", id: "q1", title: "Which branch should I use?", subtitle: "Agent of Anna", severity: "action",
  created_at: "2026-11-06T09:00:00Z", workspace: { id: "ws-1", name: "BRD team" }, text: "main or release/2.4?",
  actions: [
    { key: "main", label: "main", tone: "primary", request: { method: "POST", path: ANSWER, body: { answer: "main" } } },
    { key: "text", label: "Send answer", tone: "neutral", input: { kind: "text", label: "Your answer", placeholder: "Type an answer", required: true, field: "answer" },
      request: { method: "POST", path: ANSWER, body: {} } },
  ],
};
const RUNNING = [{ id: "r1", state: "working", current_node: "implement", work_item: { id: "wi-6", key: "BRD-6", title: "Onboarding" } }];

function server({ attention = true, items = [QUESTION], running = RUNNING } = {}) {
  const calls = [];
  const state = { items, running, refuse: null };
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    if (call.url === "/api/v1/attention") {
      if (!attention) return reply(404, { detail: "Not Found" });
      return reply(200, { items: state.items, running: state.running, count: state.items.length, cursor: null, quiet: { active: false, until: null } });
    }
    if (call.url === "/api/v1/notifications/preferences") return reply(200, { user_id: "u-alex", in_app_enabled: true, email_enabled: false });
    if (call.url === ANSWER) {
      if (state.refuse) return reply(409, { detail: { code: "already_answered", message: state.refuse } });
      state.items = state.items.filter((item) => item.id !== "q1");
      return reply(200, { ok: true });
    }
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, calls, state };
}

async function render({ srv, reducedMotion = false }) {
  const load = loader({ fetch: srv.fetch, window: windowStub({ reducedMotion }) });
  const { CompanionHost, CompanionLogoTrigger } = load("chat/companion/CompanionHost.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionHost, { userId: "u-alex", onOpenAgents: () => {}, notificationApi: null, socket: false, pollMs: 60_000, answeredMs: 0 }, createElement(CompanionLogoTrigger)));
  });
  await tick();
  return view;
}

test("the button names what needs you; a question is answered by choice and the item leaves", async () => {
  const srv = server();
  const view = await render({ srv });
  try {
    const button = byTestId(view, "octryx-button")[0];
    assert.equal(button.props["aria-label"], "Octryx: 1 needs you, 1 working");
    assert.equal(text(byTestId(view, "octryx-count")[0]), "1");
    assert.equal(button.props["data-state"], "open");
    assert.equal(button.props["data-working"], "true", "the logo breathes while a run works");
    assert.equal(button.props["data-motion"], "full");
    await act(async () => button.props.onClick());
    const panel = byTestId(view, "octryx-panel")[0];
    assert.equal(panel.props.role, "dialog", "the design system's side panel");
    assert.equal(panel.props["aria-modal"], "true");
    assert.equal(byTestId(view, "octryx-panel-backdrop").length, 1, "over the dimmed page, like every side panel");
    assert.equal(text(byTestId(view, "octryx-item")[0]).includes("main or release/2.4?"), true);
    await act(async () => byTestId(view, "octryx-action")[0].props.onClick());
    await tick();
    const sent = srv.calls.find((call) => call.url === ANSWER);
    assert.deepEqual(sent, { url: ANSWER, method: "POST", body: { answer: "main" } });
    assert.equal(byTestId(view, "octryx-item").length, 0, "success removes the item");
    assert.equal(byTestId(view, "octryx-button")[0].props["aria-label"], "Octryx: 1 working");
  } finally {
    view.unmount();
  }
});

test("free text goes into the answer field; a refusal stays on the item in the server's words", async () => {
  const srv = server();
  srv.state.refuse = "This question was already answered by Ben.";
  const view = await render({ srv });
  try {
    await act(async () => byTestId(view, "octryx-button")[0].props.onClick());
    const form = view.root.find((node) => node.type === "form");
    await act(async () => form.props.onSubmit({ preventDefault() {} }));
    assert.equal(text(byTestId(view, "octryx-refusal")[0]), "Your answer is required.", "required text is checked before sending");
    assert.equal(srv.calls.filter((call) => call.url === ANSWER).length, 0);
    await act(async () => byTestId(view, "octryx-answer-input")[0].props.onChange({ target: { value: "release/2.4" } }));
    await act(async () => form.props.onSubmit({ preventDefault() {} }));
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.url === ANSWER).map((call) => call.body), [{ answer: "release/2.4" }]);
    assert.equal(text(byTestId(view, "octryx-refusal")[0]), "This question was already answered by Ben.");
    assert.equal(byTestId(view, "octryx-item").length, 1, "a refused item stays");
    srv.state.refuse = null;
    await act(async () => view.root.find((node) => node.type === "form").props.onSubmit({ preventDefault() {} }));
    await tick();
    assert.equal(byTestId(view, "octryx-item").length, 0, "the accepted answer removes the item");
  } finally {
    view.unmount();
  }
});

test("a device approval shows its countdown and its link", async () => {
  const device = { key: "device_approval:d1", kind: "device_approval", id: "d1", title: "Approve the new device", subtitle: "MacBook",
    created_at: null, expires_at: new Date(Date.now() + 90_000).toISOString(), link: { href: "/chat?area=personal", label: "Open device prompt" } };
  const srv = server({ items: [device], running: [] });
  const view = await render({ srv });
  try {
    assert.equal(byTestId(view, "octryx-button")[0].props["aria-label"], "Octryx: 1 needs you");
    await act(async () => byTestId(view, "octryx-button")[0].props.onClick());
    const item = byTestId(view, "octryx-item")[0];
    assert.match(text(item), /Approve the new device/);
    assert.match(text(byTestId(view, "octryx-countdown")[0]), /^1:([0-2][0-9]|30) left$/);  // a loaded runner may take seconds to render
    assert.equal(item.findAll((node) => node.type === "a")[0].props.href, "/chat?area=personal");
  } finally {
    view.unmount();
  }
});

test("a failed attention read is reported in the panel and asks no other list", async () => {
  const srv = server({ attention: false });
  const view = await render({ srv });
  try {
    assert.deepEqual([...new Set(srv.calls.map((call) => call.url))].filter((url) => url !== "/api/v1/notifications/preferences"),
      ["/api/v1/attention"]);
    await act(async () => byTestId(view, "octryx-button")[0].props.onClick());
    assert.equal(text(byTestId(view, "octryx-problem")[0]), "What needs you could not be loaded.");
    assert.equal(byTestId(view, "octryx-item").length, 0);
  } finally {
    view.unmount();
  }
});

test("reduced motion keeps the logo still even while a run works", async () => {
  const view = await render({ srv: server(), reducedMotion: true });
  try {
    const button = byTestId(view, "octryx-button")[0];
    assert.equal(button.props["data-working"], "true");
    assert.equal(button.props["data-motion"], "reduced", "no breathing ring with reduced motion");
  } finally {
    view.unmount();
  }
});
