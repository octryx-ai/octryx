import assert from "node:assert/strict";
import { test } from "node:test";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";
import { initialForm, resetScope, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { scopeRefusalText } from "../../src/admin/components/workspaceKnowledge/connectorScopeText.ts";
import {
  candidatesQueryable,
  connectionHint,
  connectionOptions,
  preselectConnection,
  unlinkedWithCandidates,
} from "../../src/admin/components/workspaceKnowledge/gitConnectionModel.ts";

// "Read through connection" of a Git repository source: the server's candidates, the preselect, the body.

const SHOP = { id: "gh-shop", name: "GitHub (demo-shop org)", type: "github" };
const OTHER = { id: "gh-other", name: "GitHub bot", type: "github" };

test("only a parsable https owner/repo URL is sent for candidates", () => {
  assert.equal(candidatesQueryable("https://github.com/demo-shop/web"), true);
  assert.equal(candidatesQueryable("https://github.com/demo-shop"), false, "no repository yet: no request per keystroke");
  assert.equal(candidatesQueryable("http://github.com/demo-shop/web"), false);
  assert.equal(candidatesQueryable("github.com/demo-shop/web"), false);
});

test("exactly one candidate is preselected; none or several leave None, and the hint says what a save does", () => {
  assert.equal(preselectConnection([SHOP]), "gh-shop");
  assert.equal(preselectConnection([]), "");
  assert.equal(preselectConnection([SHOP, OTHER]), "");
  assert.match(connectionHint([SHOP], ""), /saving still links GitHub \(demo-shop org\)/,
    "None with one candidate: the server links it anyway, so the hint says so");
  assert.match(connectionHint([SHOP, OTHER], ""), /pick one/);
  assert.match(connectionHint([], ""), /read as a public repository/);
  for (const hint of [connectionHint([], ""), connectionHint([SHOP], "gh-shop")]) {
    assert.match(hint, /A private repository needs a connection with access\./);
  }
});

test("an edited source keeps a stored connection the candidates no longer list", () => {
  assert.deepEqual(connectionOptions([SHOP], "gh-shop"), [SHOP]);
  assert.deepEqual(connectionOptions([SHOP], "gone").map((option) => option.id), ["gh-shop", "gone"]);
});

function gitForm(patch = {}) {
  return { ...initialForm(null), ...resetScope("git_repository"), key: "shop-web",
    repositoryUrl: "https://github.com/demo-shop/web", ref: "main", ...patch };
}

test("the body names the chosen connection; None sends none, so the server decides by its candidates", () => {
  assert.equal(validate(gitForm({ connectionId: "gh-shop" })).config.connection_id, "gh-shop");
  assert.ok(!("connection_id" in validate(gitForm()).config));
});

test("an edited linked source saves with its connection again", () => {
  const stored = {
    connector_key: "shop-web", kind: "git_repository", connection_id: "gh-shop", state: "active", products: [],
    version: null, max_items_per_run: 50, schedule: { enabled: false, interval_minutes: 1440, next_run_at: null },
    scope: { fetch_mode: "remote_git", remote: "https://github.com/demo-shop/web", ref: "main" },
  };
  const form = initialForm(stored);
  assert.equal(form.connectionId, "gh-shop");
  const config = validate({ ...form, ref: "develop" }).config;
  assert.deepEqual([config.connection_id, config.repository_url, config.ref], ["gh-shop", "https://github.com/demo-shop/web", "develop"]);
});

test("unlinked sources with candidates get the notice; linked or candidate-less ones do not", () => {
  const source = (key, patch) => ({ connector_key: key, kind: "git_repository", ...patch });
  const listed = [
    source("open", { connection_id: null, connection_candidates: [SHOP] }),
    source("linked", { connection_id: "gh-shop" }),
    source("public", { connection_id: null, connection_candidates: [] }),
    { connector_key: "wiki", kind: "confluence" },
  ];
  assert.deepEqual(unlinkedWithCandidates(listed).map((item) => item.connector_key), ["open"]);
});

test("a refused or undecided connection is said in words", () => {
  for (const reason of ["connection_choice_required", "connection_not_available", "source_connection_not_granted",
    "repository_not_on_connection_host"]) {
    const text = scopeRefusalText({ reason });
    assert.match(text, /^Not saved: /, reason);
    assert.ok(!text.includes("_"), `${reason} has no technical name`);
  }
  assert.match(reasonText("connection_choice_required"), /Read through connection/, "the run reason points to the edit");
});
