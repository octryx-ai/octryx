// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeConnectionRepositories.test.mjs
//
// Knowledge › Sources › Add source › Git repository › "From a connection": the Bitbucket connections usable in the
// Workspace, a paged and searchable repository picker (25 per page, Previous/Next by next_start, debounced search),
// the default branch prefilled, the access mode, and "Make available in" several Workspaces: one PUT (with the
// collision-safe key derived from the repository) and one first run per Workspace. Afterwards the access mode shows
// in the list and the source panel, where an author changes it. The backend is stubbed at fetch.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { afterEach, test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  addRepositoryToWorkspaces, collisionSafeKey, defaultWorkspaceSelection, nextPage, orderedWorkspaces, previousPage,
  repositoryConnectorConfig, repositoryConnectorKey, suffixedKey, FIRST_PAGE, CONNECTOR_KEY,
} from "../../src/admin/components/workspaceKnowledge/connectionRepositoryModel.ts";
import { connectionRepositoriesApi } from "../../src/admin/components/workspaceKnowledge/connectionRepositoriesApi.ts";
import { accessModeOf, configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { connectorsApi } from "../../src/admin/components/workspaceKnowledge/connectorsApi.ts";
import { initialForm, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { gitScopeSummary } from "../../src/admin/components/workspaceKnowledge/gitRepositoryScope.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

const DC = "https://git.example.test/bitbucket/scm";
const repo = (project, slug, registered = null) => ({
  project_key: project, slug, name: `${slug} service`, repository_url: `${DC}/${project.toLowerCase()}/${slug}.git`,
  web_url: `https://git.example.test/bitbucket/projects/${project}/repos/${slug}/browse`, registered,
});

const connector = (key, remote, overrides = {}) => ({
  connector_key: key, kind: "git_repository",
  scope: { fetch_mode: "remote_git", remote, ref: "main", include_globs: ["src/**"], max_files: 300 },
  products: ["octryx"], version: null, max_items_per_run: 50, state: "active",
  cursor: { pass_number: 0, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 0 },
  schedule: { enabled: true, interval_minutes: 60, next_run_at: null }, running: false, last_run: null,
  ...overrides,
});

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body });

/** A fetch stub answering by method and URL; records every call with its parsed body. */
function backend(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const method = init.method ?? "GET";
    const call = { url: String(url), method, body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    for (const [pattern, answer] of routes) {
      const [routeMethod, routePath] = pattern.split(" ");
      if (routeMethod === method && (typeof routePath === "string" ? call.url.startsWith(routePath) && (call.url === routePath || call.url[routePath.length] === "?" || routePath.endsWith("/")) : false)) {
        return typeof answer === "function" ? answer(call) : answer;
      }
    }
    return json(404, { detail: `no stub for ${method} ${call.url}` });
  };
  return { fetch, calls };
}

// ---- the key -----------------------------------------------------------------------------------------------------

test("the connector key is bitbucket-<project>-<slug>, slugged, at most 40 characters", () => {
  assert.equal(repositoryConnectorKey("PRJ", "octryx"), "bitbucket-prj-octryx");
  assert.equal(repositoryConnectorKey("MY_PROJ", "Repo.Name__x"), "bitbucket-my-proj-repo-name-x");
  assert.equal(repositoryConnectorKey("~alex", "-dash-"), "bitbucket-alex-dash");
  const long = repositoryConnectorKey("PLATFORM", "a-very-long-repository-name-that-goes-on");
  assert.ok(long.length <= 40 && CONNECTOR_KEY.test(long), long);
  assert.equal(long, "bitbucket-platform-a-very-long-repositor");
  assert.equal(repositoryConnectorKey("P", "abcdefghijklmnopqrstuvwxyz-0123"), "bitbucket-p-abcdefghijklmnopqrstuvwxyz-0", "no dash at the end after truncation");
  assert.ok(!repositoryConnectorKey("PROJ", "x".repeat(26) + "-y").endsWith("-"));
});

test("the key is collision-safe per Workspace: same repository reuses, another repository gets -2, -3", () => {
  const url = `${DC}/octryx/app.git`;
  assert.deepEqual(collisionSafeKey("bitbucket-prj-app", url, []), { key: "bitbucket-prj-app", existing: null });
  const same = connector("bitbucket-prj-app", url);
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [same]).key, "bitbucket-prj-app");
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [same]).existing, same);
  const other = connector("bitbucket-prj-app", `${DC}/octryx/app-old.git`);
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [other]).key, "bitbucket-prj-app-2");
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [other, { ...other, connector_key: "bitbucket-prj-app-2", kind: "jira", scope: {} }]).key,
    "bitbucket-prj-app-3");
  // The same repository under another key (added earlier) is updated, not added twice.
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [other, connector("app-by-hand", url)]).key, "app-by-hand");
  // A launcher snapshot of the same remote is not this source.
  const snapshot = connector("bitbucket-prj-app", url, { scope: { fetch_mode: "local_snapshot", remote: url } });
  assert.equal(collisionSafeKey("bitbucket-prj-app", url, [snapshot]).key, "bitbucket-prj-app-2");
  // A 40-character base is truncated so the suffix fits.
  const base = "bitbucket-platform-a-very-long-repositor";
  assert.equal(suffixedKey(base, 2), "bitbucket-platform-a-very-long-reposit-2");
  assert.equal(suffixedKey(base, 2).length, 40);
  assert.equal(suffixedKey("bitbucket-platform-a-very-long-repox-abc", 12), "bitbucket-platform-a-very-long-repox-12", "no double dash");
  assert.ok(CONNECTOR_KEY.test(collisionSafeKey(base, url, [connector(base, "https://x/y/z")]).key));
});

test("a new source sends only the repository, ref, connection and access mode; an updated one keeps its settings", () => {
  const input = { repositoryUrl: `${DC}/octryx/app.git`, ref: "develop", connectionId: "bb-dc", accessMode: "read_write" };
  assert.deepEqual(repositoryConnectorConfig(input), {
    kind: "git_repository", fetch_mode: "remote_git", repository_url: `${DC}/octryx/app.git`, ref: "develop",
    connection_id: "bb-dc", access_mode: "read_write",
  });
  const updated = repositoryConnectorConfig(input, connector("bitbucket-prj-app", `${DC}/octryx/app.git`));
  assert.equal(updated.ref, "develop");
  assert.equal(updated.access_mode, "read_write");
  assert.deepEqual(updated.include_globs, ["src/**"]);
  assert.equal(updated.schedule_enabled, true);
  assert.equal(updated.max_items_per_run, 50);
});

test("the Workspaces list the current one first and check only it by default; the pager walks next_start back and forth", () => {
  const listed = orderedWorkspaces([{ id: "b", name: "Beta", current: false }, { id: "a", name: "Alpha", current: false }, { id: "c", name: "Zeta", current: true }]);
  assert.deepEqual(listed.map((workspace) => workspace.id), ["c", "a", "b"]);
  assert.deepEqual(defaultWorkspaceSelection(listed, "c"), ["c"]);
  const second = nextPage(FIRST_PAGE, 25);
  const third = nextPage(second, 50);
  assert.deepEqual(third, { start: 50, previous: [0, 25] });
  assert.deepEqual(previousPage(third), second);
  assert.deepEqual(previousPage(previousPage(third)), FIRST_PAGE);
  assert.deepEqual(nextPage(third, null), third, "the last page has no next");
});

// ---- the API -----------------------------------------------------------------------------------------------------

test("the API sends search and paging, encodes path parts, and turns a 409 into its reason", async () => {
  const { fetch, calls } = backend([
    ["GET /api/v1/workspaces/w%2F1/knowledge/connections/bb%20dc/repositories", json(200, { repositories: [], start: 0, limit: 25, next_start: null, is_last_page: true })],
    ["GET /api/v1/workspaces/w%2F1/knowledge/connections/bb%20dc/repositories/", json(200, { default_branch: "main" })],
    ["GET /api/v1/workspaces/w%2F1/knowledge/connections", json(409, { detail: { state: "refused", reason: "connection_disabled" } })],
  ]);
  globalThis.fetch = fetch;
  await connectionRepositoriesApi.repositories("w/1", "bb dc", { q: " core api ", start: 25 });
  assert.equal(calls[0].url, "/api/v1/workspaces/w%2F1/knowledge/connections/bb%20dc/repositories?q=core+api&start=25&limit=25");
  assert.deepEqual(await connectionRepositoriesApi.defaultBranch("w/1", "bb dc", "~ALEX", "a/b"), { default_branch: "main" });
  assert.equal(calls[1].url, "/api/v1/workspaces/w%2F1/knowledge/connections/bb%20dc/repositories/~ALEX/a%2Fb/default-branch");
  await assert.rejects(connectionRepositoriesApi.connections("w/1"), (error) => {
    assert.equal(error.reason, "connection_disabled");
    assert.equal(error.message, "Refused: the connection is disabled.");
    return true;
  });
});

// ---- saving to several Workspaces --------------------------------------------------------------------------------

test("saving to several Workspaces: one PUT with the collision-safe key and one first run each; refusals are per Workspace", async () => {
  const repository = repo("PRJ", "app");
  const { fetch, calls } = backend([
    ["GET /api/v1/workspaces/ws-1/knowledge/connectors", json(200, { connectors: [connector("bitbucket-prj-app", `${DC}/octryx/other.git`)] })],
    ["GET /api/v1/workspaces/ws-2/knowledge/connectors", json(200, { connectors: [] })],
    ["GET /api/v1/workspaces/ws-3/knowledge/connectors", json(200, { connectors: [] })],
    ["PUT /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app-2", (call) => json(200, { connector_key: "bitbucket-prj-app-2", ...call.body })],
    ["PUT /api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-app", (call) => json(200, { connector_key: "bitbucket-prj-app", ...call.body })],
    ["PUT /api/v1/workspaces/ws-3/knowledge/connectors/bitbucket-prj-app", json(409, { detail: { state: "refused", reason: "connection_not_available" } })],
    ["POST /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app-2/runs", json(200, { id: "r1", state: "completed", reason: null, report: { failed: 0 } })],
    ["POST /api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-app/runs", json(409, { detail: { state: "refused", reason: "egress_refused" } })],
  ]);
  globalThis.fetch = fetch;
  const progress = [];
  const results = await addRepositoryToWorkspaces({
    workspaces: [{ id: "ws-1", name: "Alpha", current: true }, { id: "ws-2", name: "Beta", current: false }, { id: "ws-3", name: "Gamma", current: false }],
    repository, ref: "main", connectionId: "bb-dc", accessMode: "read_only",
  }, { onProgress: (snapshot) => progress.push(snapshot) });

  const puts = calls.filter((call) => call.method === "PUT");
  assert.deepEqual(puts.map((call) => call.url), [
    "/api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app-2",
    "/api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-app",
    "/api/v1/workspaces/ws-3/knowledge/connectors/bitbucket-prj-app",
  ]);
  for (const put of puts) {
    assert.deepEqual(put.body, {
      kind: "git_repository", fetch_mode: "remote_git", repository_url: repository.repository_url, ref: "main",
      connection_id: "bb-dc", access_mode: "read_only",
    });
  }
  assert.deepEqual(calls.filter((call) => call.method === "POST").map((call) => call.url), [
    "/api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app-2/runs",
    "/api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-app/runs",
  ], "one run per saved Workspace, none for the refused one");

  assert.deepEqual(results.map((result) => [result.workspaceId, result.state, result.connectorKey, result.run]), [
    ["ws-1", "saved", "bitbucket-prj-app-2", "started"],
    ["ws-2", "saved", "bitbucket-prj-app", "failed"],
    ["ws-3", "refused", "bitbucket-prj-app", "not_started"],
  ]);
  assert.equal(results[2].reason, "connection_not_available");
  assert.match(results[2].problem, /not available to this Workspace/);
  assert.match(results[1].runText, /^First sync not started: Refused: outbound connection refused/);
  assert.ok(progress.some((snapshot) => snapshot.some((result) => result.run === "running")), "the save reports progress");
});

// ---- the existing form's re-save and pause keep the connection ----------------------------------------------------

test("a repository added from a connection is re-saved and paused with its connection; the access mode is left out", () => {
  const connected = connector("bitbucket-prj-app", `${DC}/octryx/app.git`, { connection_id: "bb-dc", access_mode: "read_write", scope: {
    fetch_mode: "remote_git", remote: `${DC}/octryx/app.git`, ref: "main", access_mode: "read_write",
  } });
  assert.equal(accessModeOf(connected), "read_write");
  assert.equal(accessModeOf({ ...connected, access_mode: undefined }), "read_write", "read from the scope too");
  assert.equal(accessModeOf(connector("x", "https://github.com/a/b")), null);

  const paused = configOf(connected, "paused");
  assert.equal(paused.connection_id, "bb-dc");
  assert.equal("access_mode" in paused, false);
  assert.equal("connection_id" in configOf(connector("x", "https://github.com/a/b")), false, "a public repository is unchanged");

  const form = initialForm(connected);
  assert.equal(form.connectionId, "bb-dc");
  const checked = validate({ ...form, ref: "develop" });
  assert.ok("config" in checked, JSON.stringify(checked));
  assert.equal(checked.config.connection_id, "bb-dc");
  assert.equal(checked.config.repository_url, `${DC}/octryx/app.git`, "a Data Center URL is accepted with its connection");
  assert.equal("access_mode" in checked.config, false);
  assert.equal(gitScopeSummary(connected.scope).repository, "octryx/app");
});

// ---- rendered ----------------------------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
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

const PAGE_ONE = Array.from({ length: 25 }, (_, index) => repo("PRJ", `svc-${String(index + 1).padStart(2, "0")}`));
const PAGE_TWO = [repo("PRJ", "svc-26"), repo("PRJ", "app", { connector_key: "bitbucket-prj-app", access_mode: "read_write" })];

function pickerBackend(extra = []) {
  return backend([
    ...extra,
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/repositories/", json(200, { default_branch: "develop" })],
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/repositories", (call) => {
      const params = new URL(call.url, "http://x").searchParams;
      const q = params.get("q");
      if (q) return json(200, { repositories: [repo("PRJ", "app")], start: 0, limit: 25, next_start: null, is_last_page: true });
      return params.get("start") === "25"
        ? json(200, { repositories: PAGE_TWO, start: 25, limit: 25, next_start: null, is_last_page: true })
        : json(200, { repositories: PAGE_ONE, start: 0, limit: 25, next_start: 25, is_last_page: false });
    }],
    ["GET /api/v1/workspaces/ws-1/knowledge/connections/bb-dc/workspaces", json(200, { workspaces: [
      { id: "ws-2", name: "Beta", current: false }, { id: "ws-1", name: "Alpha", current: true },
    ] })],
    ["GET /api/v1/workspaces/ws-1/knowledge/connections", json(200, { connections: [
      { id: "bb-dc", name: "Example Corp Bitbucket", type: "bitbucket", deployment: "datacenter", host: "git.example.test" },
    ] })],
  ]);
}

const CONNECTIONS = [{ id: "bb-dc", name: "Example Corp Bitbucket", type: "bitbucket", deployment: "datacenter", host: "git.example.test" }];
const rows = (view) => byTestId(view, "connection-repo-row").map((row) => row.props["data-repository"]);
const repositoryCalls = (calls) => calls.filter((call) => call.method === "GET" && /\/repositories\?/.test(call.url))
  .map((call) => Object.fromEntries(new URL(call.url, "http://x").searchParams));
const click = async (node) => { await act(async () => { node.props.onClick(); }); };

test("rendered: the picker pages with Next/Previous and searches with q after a pause", async () => {
  const { fetch, calls } = pickerBackend();
  const { KnowledgeConnectionRepositoryForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectionRepositoryForm.tsx", { fetch });
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeConnectionRepositoryForm, { workspaceId: "ws-1", connections: CONNECTIONS, onSaved: () => {}, onCancel: () => {} }));
  });
  assert.equal(rows(view).length, 25);
  assert.equal(rows(view)[0], "PRJ/svc-01");
  assert.equal(text(byTestId(view, "connection-repo-range")[0]), "1–25");
  assert.equal(byTestId(view, "connection-repo-previous")[0].props.disabled, true);

  await click(byTestId(view, "connection-repo-next")[0]);
  assert.deepEqual(rows(view), ["PRJ/svc-26", "PRJ/app"]);
  assert.equal(text(byTestId(view, "connection-repo-range")[0]), "26–27");
  assert.equal(byTestId(view, "connection-repo-next")[0].props.disabled, true, "the last page");
  const registered = byTestId(view, "connection-repo-registered");
  assert.equal(registered.length, 1);
  assert.equal(text(registered[0]), "Read & write", "an already registered repository shows its access mode");

  await click(byTestId(view, "connection-repo-previous")[0]);
  assert.equal(rows(view)[0], "PRJ/svc-01");
  assert.deepEqual(repositoryCalls(calls).map((params) => params.start), ["0", "25", "0"]);
  assert.ok(repositoryCalls(calls).every((params) => params.limit === "25"));

  await act(async () => { byTestId(view, "connection-repo-search")[0].props.onChange({ target: { value: "ap" } }); });
  await act(async () => { byTestId(view, "connection-repo-search")[0].props.onChange({ target: { value: "app" } }); });
  assert.equal(repositoryCalls(calls).length, 3, "no request while typing");
  await act(async () => { await sleep(360); });
  assert.deepEqual(repositoryCalls(calls).at(-1), { q: "app", start: "0", limit: "25" });
  assert.equal(repositoryCalls(calls).length, 4, "one request for the pause, not one per keystroke");
  assert.deepEqual(rows(view), ["PRJ/app"]);
  act(() => view.unmount());
});

test("rendered: choosing a repository prefills its default branch; two Workspaces get one PUT and one run each", async () => {
  const { fetch, calls } = pickerBackend([
    ["GET /api/v1/workspaces/ws-1/knowledge/connectors", json(200, { connectors: [connector("bitbucket-prj-svc-01", `${DC}/prj/elsewhere.git`)] })],
    ["GET /api/v1/workspaces/ws-2/knowledge/connectors", json(200, { connectors: [] })],
    ["PUT /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-svc-01-2", (call) => json(200, call.body)],
    ["PUT /api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-svc-01", json(409, { detail: { state: "refused", reason: "repository_not_on_connection_host" } })],
    ["POST /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-svc-01-2/runs", json(200, { id: "r", state: "completed", reason: null, report: {} })],
  ]);
  const { KnowledgeConnectionRepositoryForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectionRepositoryForm.tsx", { fetch });
  let saved = 0;
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeConnectionRepositoryForm, { workspaceId: "ws-1", connections: CONNECTIONS, onSaved: () => { saved += 1; }, onCancel: () => {} }));
  });
  const radio = view.root.findAll((node) => node.type === "input" && node.props.name === "connection-repository")[0];
  await act(async () => { radio.props.onChange(); });
  assert.equal(byTestId(view, "connection-repo-branch")[0].props.value, "develop", "prefilled with the default branch");
  assert.ok(calls.some((call) => call.url === "/api/v1/workspaces/ws-1/knowledge/connections/bb-dc/repositories/PRJ/svc-01/default-branch"));

  const workspaces = byTestId(view, "connection-workspace");
  assert.deepEqual(workspaces.map((node) => node.props["data-workspace"]), ["ws-1", "ws-2"], "the current Workspace first");
  const checkbox = (id) => workspaces.find((node) => node.props["data-workspace"] === id).findByType("input");
  assert.equal(checkbox("ws-1").props.checked, true);
  assert.equal(checkbox("ws-2").props.checked, false);
  await act(async () => { checkbox("ws-2").props.onChange({ target: { checked: true } }); });
  assert.equal(byTestId(view, "connection-access-read_only")[0].props.checked, true, "read only by default");
  await act(async () => { byTestId(view, "connection-access-read_write")[0].props.onChange(); });
  await act(async () => { byTestId(view, "connection-repo-branch")[0].props.onChange({ target: { value: "release/1.0" } }); });
  assert.equal(text(byTestId(view, "connection-repo-save")[0]), "Add to 2 Workspaces");

  await click(byTestId(view, "connection-repo-save")[0]);
  const puts = calls.filter((call) => call.method === "PUT");
  assert.deepEqual(puts.map((call) => call.url), [
    "/api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-svc-01-2",
    "/api/v1/workspaces/ws-2/knowledge/connectors/bitbucket-prj-svc-01",
  ]);
  assert.deepEqual(puts[0].body, {
    kind: "git_repository", fetch_mode: "remote_git", repository_url: `${DC}/prj/svc-01.git`, ref: "release/1.0",
    connection_id: "bb-dc", access_mode: "read_write",
  });
  assert.deepEqual(calls.filter((call) => call.method === "POST").map((call) => call.url),
    ["/api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-svc-01-2/runs"]);
  const results = byTestId(view, "connection-save-result");
  assert.deepEqual(results.map((node) => [node.props["data-workspace"], node.props["data-state"]]), [["ws-1", "saved"], ["ws-2", "refused"]]);
  assert.match(text(results[0]), /^Alpha: Saved as bitbucket-prj-svc-01-2\. First sync: The run completed a full pass\.$/);
  assert.match(text(results[1]), /^Beta: Refused: the repository is not on the connection's host\.$/);
  assert.equal(saved, 1, "the list reloads after a save that reached a Workspace");
  act(() => view.unmount());
});

test("rendered: the connector form offers 'From a connection' only when a connection is usable", async () => {
  const withConnection = pickerBackend();
  const { KnowledgeConnectorForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectorForm.tsx", { fetch: withConnection.fetch });
  const props = { editing: null, busy: false, onSave: async () => true, onCancel: () => {}, workspaceId: "ws-1" };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeConnectorForm, props)); });
  const kind = view.root.findAll((node) => node.type === "select" && node.props["aria-label"] === "Source system")[0];
  await act(async () => { kind.props.onChange({ target: { value: "git_repository" } }); });
  assert.equal(byTestId(view, "repository-from").length, 1);
  assert.equal(view.root.findAll((node) => node.props["aria-label"] === "Repository URL").length, 1, "the public URL entry stays the default");
  await act(async () => { byTestId(view, "repository-from-connection")[0].props.onChange(); });
  assert.equal(byTestId(view, "connection-repo-form").length, 1);
  assert.equal(view.root.findAll((node) => node.props["aria-label"] === "Connector name").length, 0, "the name is derived");
  assert.equal(rows(view).length, 25);
  act(() => view.unmount());

  const none = backend([["GET /api/v1/workspaces/ws-1/knowledge/connections", json(403, { detail: "Forbidden" })]]);
  const reader = load("admin/components/workspaceKnowledge/KnowledgeConnectorForm.tsx", { fetch: none.fetch });
  await act(async () => { view = TestRenderer.create(createElement(reader.KnowledgeConnectorForm, props)); });
  const select = view.root.findAll((node) => node.type === "select" && node.props["aria-label"] === "Source system")[0];
  await act(async () => { select.props.onChange({ target: { value: "git_repository" } }); });
  assert.equal(byTestId(view, "repository-from").length, 0, "no usable connection: only the public URL");
  act(() => view.unmount());
});

test("rendered: the access mode shows in the list and the panel, and an author changes it there", async () => {
  const connected = connector("bitbucket-prj-app", `${DC}/octryx/app.git`, { connection_id: "bb-dc", access_mode: "read_only" });
  const { fetch, calls } = backend([
    ["PUT /api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app/access-mode", (call) => json(200, { ...connected, access_mode: call.body.access_mode })],
  ]);
  const { SourceDetailPanel } = load("admin/components/workspaceKnowledge/sources/SourceDetailPanel.tsx", { fetch, window: undefined });
  const changed = [];
  const props = {
    connector: connected, workspaceId: "ws-1", lastRun: null, running: false, busy: false, mayAuthor: true, schedulingOn: true,
    instance: "on", onClose: () => {}, onRun: () => {}, onEdit: () => {}, mode: "page", onAccessModeChanged: (described) => changed.push(described),
  };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(SourceDetailPanel, props)); });
  const select = byTestId(view, "source-access-mode")[0];
  assert.equal(select.props.value, "read_only");
  assert.match(text(view.root.findByProps({ "data-testid": "source-overview" })), /Through the connection bb-dc/);
  assert.equal(byTestId(view, "source-access-mode-save").length, 0, "nothing to save yet");
  await act(async () => { select.props.onChange({ target: { value: "read_write" } }); });
  await click(byTestId(view, "source-access-mode-save")[0]);
  const put = calls.find((call) => call.method === "PUT");
  assert.equal(put.url, "/api/v1/workspaces/ws-1/knowledge/connectors/bitbucket-prj-app/access-mode");
  assert.deepEqual(put.body, { access_mode: "read_write" });
  assert.equal(changed[0].access_mode, "read_write");
  act(() => view.unmount());

  await act(async () => { view = TestRenderer.create(createElement(SourceDetailPanel, { ...props, mayAuthor: false })); });
  assert.equal(text(byTestId(view, "source-access-mode")[0]), "Read only", "readers see it, without a control");
  act(() => view.unmount());

  const { KnowledgeSourceList } = load("admin/components/workspaceKnowledge/sources/KnowledgeSourceList.tsx");
  const actions = { onRun() {}, onShow() {}, onEdit() {}, onToggle() {}, onReleases() {}, onDelete() {}, onOpenUploads() {} };
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeSourceList, {
      connectors: [{ ...connected, access_mode: "read_write" }, connector("public", "https://github.com/a/b")],
      selectedKey: null, busy: false, runningKey: null, mayAuthor: true, actions,
    }));
  });
  const labels = byTestId(view, "knowledge-source-access");
  assert.deepEqual(labels.map(text), ["Read & write"], "only the repository read through a connection carries one");
  act(() => view.unmount());
});

test("configure accepts the connection repository body unchanged", async () => {
  const { fetch, calls } = backend([["PUT /api/v1/workspaces/ws/knowledge/connectors/k", (call) => json(200, call.body)]]);
  globalThis.fetch = fetch;
  const body = repositoryConnectorConfig({ repositoryUrl: `${DC}/octryx/app.git`, ref: "main", connectionId: "bb-dc", accessMode: "read_only" });
  await connectorsApi.configure("ws", "k", body);
  assert.deepEqual(calls[0].body, body);
});
