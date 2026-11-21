// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionReload.test.mjs
//
// How often the companion reads GET /api/v1/attention (17 parallel runs caused ~1.6 reads per second,
// because every run event nudged the requester and every nudge read at once): a burst reads at most once per gap
// (leading + trailing), the interval poll is only the fallback while the socket is closed, a hidden tab reads
// nothing until it is shown again, and a failing server is polled less and less often.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  COMPANION_POLL_MS, createThrottle, ERROR_BACKOFF_MAX_MS, NUDGE_MIN_GAP_MS, pollDelayMs, SAFETY_POLL_MS,
} from "../../src/chat/companion/companionReload.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const tick = (ms = 0) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

function fakeClock() {
  let now = 0;
  let timers = [];
  return {
    now: () => now,
    setTimeout: (run, ms) => { const timer = { at: now + ms, run }; timers.push(timer); return timer; },
    clearTimeout: (timer) => { timers = timers.filter((item) => item !== timer); },
    advance(ms) {
      now += ms;
      for (const timer of timers.filter((item) => item.at <= now)) { timers = timers.filter((item) => item !== timer); timer.run(); }
    },
  };
}

test("a burst of nudges reads at once and once more at the end of the gap, never more", () => {
  const clock = fakeClock();
  let reads = 0;
  const throttle = createThrottle(() => { reads += 1; }, NUDGE_MIN_GAP_MS, clock);
  for (let index = 0; index < 20; index += 1) { throttle.request(); clock.advance(200); }
  assert.equal(reads, 1, "20 nudges in 4 s: the first reads at once");
  clock.advance(NUDGE_MIN_GAP_MS);
  assert.equal(reads, 2, "the rest fold into one read at the end of the gap");
  clock.advance(60_000);
  assert.equal(reads, 2, "nothing more without a new nudge");
  throttle.request();
  assert.equal(reads, 3, "a nudge after a quiet gap reads at once");
});

test("the poll is the fallback while the socket is closed, a safety net while it is open, and backs off on errors", () => {
  assert.equal(pollDelayMs({ socketOpen: false, failures: 0 }), COMPANION_POLL_MS);
  assert.equal(pollDelayMs({ socketOpen: true, failures: 0 }), SAFETY_POLL_MS);
  assert.equal(pollDelayMs({ socketOpen: false, failures: 1 }), 2 * COMPANION_POLL_MS);
  assert.equal(pollDelayMs({ socketOpen: false, failures: 2 }), 4 * COMPANION_POLL_MS);
  assert.equal(pollDelayMs({ socketOpen: true, failures: 9 }), ERROR_BACKOFF_MAX_MS, "capped");
});

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

function windowStub() {
  const target = new EventTarget();
  return {
    location: { origin: "http://localhost", protocol: "http:", host: "localhost", search: "?workspace_id=ws-1", href: "http://localhost/chat" },
    localStorage: { getItem: () => null, setItem() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    dispatchEvent: (event) => target.dispatchEvent(event),
  };
}

function socketStub() {
  const sockets = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(message) { this.sent.push(message); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; this.onopen?.(); }
    push(message) { this.onmessage?.({ data: JSON.stringify(message) }); }
  }
  return { FakeSocket, sockets };
}


function server() {
  const calls = [];
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url) => {
    const parsed = new URL(String(url), "http://localhost");
    calls.push(parsed.pathname);
    if (parsed.pathname === "/api/v1/attention") return reply(200, { items: [], running: [], count: 0, cursor: null, quiet: { active: false, until: null } });
    if (parsed.pathname === "/api/v1/notifications/preferences") return reply(200, { user_id: "u-alex", in_app_enabled: true });
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, reads: () => calls.filter((call) => call === "/api/v1/attention").length };
}

async function mount(srv, doc) {
  const { FakeSocket, sockets } = socketStub();
  const load = loader({ fetch: srv.fetch, window: windowStub(), WebSocket: FakeSocket, document: doc });
  const { CompanionHost } = load("chat/companion/CompanionHost.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionHost, { userId: "u-alex", onOpenAgents: () => {}, notificationApi: null, pollMs: 60_000 }));
  });
  await tick();
  await act(async () => sockets[0].open());
  return { view, socket: sockets[0] };
}

function documentStub(hidden) {
  const target = new EventTarget();
  return {
    hidden,
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    show() { this.hidden = false; target.dispatchEvent(new Event("visibilitychange")); },
  };
}

test("twenty socket nudges in a row read the attention queue once, not twenty times", async () => {
  const srv = server();
  const { view, socket } = await mount(srv, documentStub(false));
  const before = srv.reads();
  await act(async () => { for (let index = 0; index < 20; index += 1) socket.push({ type: "attention_changed" }); });
  await tick();
  assert.equal(srv.reads() - before, 1, "the first nudge reads; the others wait for the end of the gap");
  await act(async () => view.unmount());
});

test("a hidden tab reads nothing on nudges and catches up once when it is shown", async () => {
  const srv = server();
  const doc = documentStub(true);
  const { view, socket } = await mount(srv, doc);
  const before = srv.reads();
  await act(async () => { for (let index = 0; index < 5; index += 1) socket.push({ type: "attention_changed" }); });
  await tick();
  assert.equal(srv.reads() - before, 0, "hidden: no read");
  await act(async () => doc.show());
  await tick();
  assert.equal(srv.reads() - before, 1, "shown again: one read");
  await act(async () => view.unmount());
});
