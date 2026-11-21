// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionLogo.test.mjs
//
// Octryx lives in the logo at the top left (product inventory, step 1): the real Octryx AI logo as clean vector
// paths (no embedded raster), the logo as the companion's trigger with the count as a dot, no floating button, and
// the logo's old "open chat" link kept where no companion host is mounted.
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
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");

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

const windowStub = () => ({
  location: { origin: "http://localhost", protocol: "http:", host: "localhost", search: "", href: "http://localhost/chat" },
  localStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
});

const PROBLEM = { key: "problem:p1", kind: "problem", id: "p1", title: "CI failed", severity: "problem", created_at: "2026-11-06T09:00:00Z", actions: [] };
const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
const fetchStub = async (url) => {
  if (String(url) === "/api/v1/attention") {
    return reply(200, { items: [PROBLEM], running: [], count: 1, cursor: null, quiet: { active: false, until: null } });
  }
  if (String(url) === "/api/v1/notifications/preferences") return reply(200, { user_id: "u-alex", in_app_enabled: true });
  return reply(404, { detail: "Not Found" });
};

test("the logo is the real Octryx AI logo as vector paths, without an embedded raster", () => {
  const asset = fs.readFileSync(path.join(SRC, "assets/octryx-logo.vector.svg"), "utf8");
  assert.doesNotMatch(asset, /<image|data:image|base64/);
  assert.match(asset, /viewBox="0 0 100 100"/);
  assert.match(asset, /fill="currentColor"/);
  const paths = read("chat/companion/octryxLogoPaths.ts");
  for (const d of asset.match(/ d="([^"]+)"/g)) assert.ok(paths.includes(d.slice(4, -1)), "the component draws the asset's paths");
  assert.ok(asset.length < 20_000, "small enough to inline");
});

test("the logo in the rail and in the compact menu is the trigger; the floating button is gone", () => {
  const view = read("chat/AppContainerView.tsx");
  assert.doesNotMatch(view, /<CompanionButton/, "no bottom-right mount");
  assert.match(view, /<CompanionHost[\s\S]*<\/CompanionHost>/, "one host around the shell");
  assert.match(read("chat/AreaRail.tsx"), /<CompanionLogoTrigger className="area-rail__logo"/);
  assert.match(read("chat/CompactAreaMenu.tsx"), /<CompanionLogoTrigger/, "reachable where the rail is hidden");
  const css = read("chat/companion/companion.css");
  assert.doesNotMatch(css, /\.octryx-companion\s*\{/, "no fixed bottom-right wrapper");
  assert.doesNotMatch(read("chat/companion/CompanionHost.tsx"), /OctryxOctopus/, "no self-drawn octopus");
});

test("a click on the logo opens the side panel; the dot counts what needs you plus problems", async () => {
  const load = loader({ fetch: fetchStub, window: windowStub() });
  const { CompanionHost, CompanionLogoTrigger } = load("chat/companion/CompanionHost.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionHost, { userId: "u-alex", onOpenAgents: () => {}, notificationApi: null, socket: false, pollMs: 60_000 },
      createElement(CompanionLogoTrigger, { className: "area-rail__logo" })));
  });
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  try {
    const trigger = byTestId(view, "octryx-button")[0];
    assert.equal(trigger.type, "button");
    assert.equal(trigger.props["aria-label"], "Octryx: 1 problem");
    assert.equal(trigger.props["aria-expanded"], false);
    assert.equal(trigger.props["data-state"], "worry");
    assert.equal(byTestId(view, "octryx-count")[0].children.join(""), "1");
    assert.ok(trigger.findAll((node) => node.type === "path").length === 2, "the logo, drawn as two vector paths");
    assert.equal(byTestId(view, "octryx-panel").length, 0);
    await act(async () => trigger.props.onClick());
    // The design system's side panel over the dimmed page.
    assert.equal(byTestId(view, "octryx-panel")[0].props.role, "dialog");
    assert.equal(byTestId(view, "octryx-panel-backdrop").length, 1);
    assert.equal(byTestId(view, "octryx-button")[0].props["aria-expanded"], true);
  } finally {
    view.unmount();
  }
});

test("without a companion host the logo stays the link to chat", async () => {
  const load = loader({ fetch: fetchStub, window: windowStub() });
  const { CompanionLogoTrigger } = load("chat/companion/CompanionHost.tsx");
  const view = TestRenderer.create(createElement(CompanionLogoTrigger, {}));
  const link = view.root.findByType("a");
  assert.equal(link.props.href, "/chat");
  assert.equal(link.props["aria-label"], "Open chat");
  view.unmount();
});
