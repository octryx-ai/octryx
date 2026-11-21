// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeRepositoryGitToken.test.mjs
//
// A Bitbucket Data Center repository's own Git token (Data Center answers 500 on Git over HTTPS for
// the connection's OpenID Connect token). "From a connection" offers an optional password field and sends the token
// with the PUT only when one was entered; an existing source shows "Git token configured · Replace · Remove" and
// replaces (PUT /git-token) or removes (DELETE /git-token) it. The token is never rendered. The backend is stubbed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { afterEach, test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { repositoryConnectorConfig } from "../../src/admin/components/workspaceKnowledge/connectionRepositoryModel.ts";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";
import { takesGitToken } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const click = async (node) => { await act(async () => { node.props.onClick(); }); };
const TOKEN = "BBDC-secret-token-value";
const DC = "https://git.example.test/bitbucket";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body });

function backend(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const method = init.method ?? "GET";
    const call = { url: String(url), method, body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    for (const [pattern, answer] of routes) {
      const [routeMethod, routePath] = pattern.split(" ");
      if (routeMethod === method && (call.url === routePath || call.url.startsWith(`${routePath}?`))) {
        return typeof answer === "function" ? answer(call) : answer;
      }
    }
    return json(404, { detail: `no stub for ${method} ${call.url}` });
  };
  return { fetch, calls };
}

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Promise, JSON,
      setTimeout, clearTimeout, ...extra,
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

const connected = (gitToken) => ({
  connector_key: "bitbucket-prj-app", kind: "git_repository",
  scope: { fetch_mode: "remote_git", remote: `${DC}/projects/PRJ/repos/app`, ref: "main", host: "bitbucket_datacenter",
    host_base: DC, access_mode: "read_write" },
  products: [], version: null, max_items_per_run: 100, state: "active",
  cursor: { pass_number: 0, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 0 },
  schedule: { enabled: false, interval_minutes: 360, next_run_at: null }, running: false, last_run: null,
  connection_id: "bb-dc", access_mode: "read_write", git_token: gitToken,
});

test("the PUT carries git_token only when one was entered", () => {
  const input = { repositoryUrl: `${DC}/scm/prj/app.git`, ref: "main", connectionId: "bb-dc", accessMode: "read_only" };
  assert.equal("git_token" in repositoryConnectorConfig(input), false);
  assert.equal("git_token" in repositoryConnectorConfig({ ...input, gitToken: "   " }), false, "blank keeps the stored token");
  assert.equal(repositoryConnectorConfig({ ...input, gitToken: ` ${TOKEN} ` }).git_token, TOKEN);
});

test("only a Data Center repository through a connection takes a token; refusals read plainly", () => {
  assert.equal(takesGitToken(connected({ configured: false })), true);
  assert.equal(takesGitToken({ ...connected(undefined), scope: { fetch_mode: "remote_git", remote: "https://github.com/a/b" }, connection_id: null }), false);
  assert.match(reasonText("git_token_invalid"), /rejected the Git access token/);
  assert.match(reasonText("git_token_wrong_repository"), /does not reach this repository/);
});

test("rendered: the form offers a password field for a Data Center connection and sends the token", async () => {
  const repository = { project_key: "PRJ", slug: "app", name: "app", repository_url: `${DC}/scm/prj/app.git`, web_url: null, registered: null };
  const { fetch, calls } = backend([
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/repositories", json(200, { repositories: [repository], start: 0, limit: 25, next_start: null, is_last_page: true })],
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/repositories/PRJ/app/default-branch", json(200, { default_branch: "main" })],
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/workspaces", json(200, { workspaces: [{ id: "ws-1", name: "Alpha", current: true }] })],
    ["GET /api/v1/workspaces/ws-1/knowledge/connectors", json(200, { connectors: [] })],
    ["PUT /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app", (call) => json(200, { connector_key: "bitbucket-prj-app" })],
    ["POST /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app/runs", json(200, { id: "r", state: "completed", reason: null, report: {} })],
  ]);
  const { KnowledgeConnectionRepositoryForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectionRepositoryForm.tsx", { fetch });
  const connections = [{ id: "bb-dc", name: "Bitbucket", type: "bitbucket", deployment: "datacenter", host: "git.example.test" }];
  let view;
  let saved = 0;
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeConnectionRepositoryForm, {
      workspaceId: "ws-1", connections, onSaved: () => { saved += 1; }, onCancel: () => {} }));
  });
  assert.equal(byTestId(view, "connection-repo-git-token").length, 0, "no field before a repository is chosen");
  const radio = view.root.findAll((node) => node.type === "input" && node.props.type === "radio" && node.props.name === "connection-repository")[0];
  await act(async () => { radio.props.onChange(); });
  const [field] = byTestId(view, "connection-repo-git-token");
  assert.equal(field.props.type, "password");
  assert.match(text(view.root), /Git access token \(Bitbucket HTTP access token, Repository write\)/);
  assert.equal(byTestId(view, "connection-repo-git-token-help").length, 1);
  await act(async () => { field.props.onChange({ target: { value: TOKEN } }); });
  await click(byTestId(view, "connection-repo-save")[0]);
  const put = calls.find((call) => call.method === "PUT");
  assert.equal(put.body.git_token, TOKEN);
  assert.equal(saved, 1);
  assert.equal(byTestId(view, "connection-repo-git-token")[0].props.value, "", "the token is cleared after the save");
  act(() => view.unmount());

  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeConnectionRepositoryForm, {
      workspaceId: "ws-1", connections: [{ ...connections[0], deployment: "cloud" }], onSaved: () => {}, onCancel: () => {} }));
  });
  const cloudRadio = view.root.findAll((node) => node.type === "input" && node.props.name === "connection-repository")[0];
  await act(async () => { cloudRadio.props.onChange(); });
  assert.equal(byTestId(view, "connection-repo-git-token").length, 0, "Bitbucket Cloud reads with its API token");
  act(() => view.unmount());
});

test("rendered: an existing source shows Git token configured · Replace · Remove, never the token", async () => {
  const configured = connected({ configured: true, set_at: "2026-11-08T10:00:00+00:00", set_by: "u1" });
  const { fetch, calls } = backend([
    ["PUT /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app/git-token", (call) => call.body.git_token === "bad-token-123"
      ? json(409, { detail: { state: "refused", reason: "git_token_wrong_repository" } })
      : json(200, connected({ configured: true, set_at: "2026-11-08T11:00:00+00:00", set_by: "u1" }))],
    ["DELETE /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app/git-token", json(200, connected({ configured: false }))],
  ]);
  const { SourceGitToken } = load("admin/components/workspaceKnowledge/sources/SourceGitToken.tsx", { fetch, window: undefined });
  const changed = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(SourceGitToken, { connector: configured, workspaceId: "ws-1", editable: true,
      onChanged: (described) => changed.push(described) }));
  });
  assert.match(text(byTestId(view, "source-git-token-state")[0]), /^Git token configured/);
  assert.equal(text(byTestId(view, "source-git-token-replace")[0]), "Replace");
  assert.equal(text(byTestId(view, "source-git-token-remove")[0]), "Remove");

  await click(byTestId(view, "source-git-token-replace")[0]);
  const input = byTestId(view, "source-git-token-input")[0];
  assert.equal(input.props.type, "password");
  await act(async () => { input.props.onChange({ target: { value: "bad-token-123" } }); });
  await click(byTestId(view, "source-git-token-save")[0]);
  assert.match(text(view.root), /does not reach this repository/);
  assert.equal(changed.length, 0);
  await act(async () => { byTestId(view, "source-git-token-input")[0].props.onChange({ target: { value: TOKEN } }); });
  await click(byTestId(view, "source-git-token-save")[0]);
  assert.deepEqual(calls.filter((call) => call.method === "PUT").map((call) => call.body), [{ git_token: "bad-token-123" }, { git_token: TOKEN }]);
  assert.equal(changed.length, 1);
  assert.equal(byTestId(view, "source-git-token-input").length, 0, "the field closes after the save");
  assert.ok(!JSON.stringify(view.toJSON()).includes(TOKEN), "the token is never rendered");

  await click(byTestId(view, "source-git-token-remove")[0]);
  assert.equal(calls.at(-1).method, "DELETE");
  assert.equal(changed.at(-1).git_token.configured, false);
  act(() => view.unmount());

  await act(async () => {
    view = TestRenderer.create(createElement(SourceGitToken, { connector: connected({ configured: false }), workspaceId: "ws-1", editable: false }));
  });
  assert.match(text(byTestId(view, "source-git-token-state")[0]), /No Git token/);
  assert.equal(byTestId(view, "source-git-token-replace").length, 0, "readers get no control");
  act(() => view.unmount());
});
