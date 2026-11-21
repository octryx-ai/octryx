import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  addEntry,
  applyRefusal,
  draftsFromPayload,
  entriesOf,
  entryShapeRefusal,
  loadFailureCode,
  parsePrivateHostRefusal,
  removeEntry,
} from "../../src/admin/components/connectorsTab/privateHostAllowlistModel.ts";
import {
  PRIVATE_HOSTS_PATH,
  savePrivateHostEntries,
} from "../../src/admin/components/connectorsTab/privateHostAllowlistApi.ts";

// The GET body and the 400 refusal of backend/app/web/routers/panel_egress.py.
const LISTED = {
  allowlistable: ["bitbucket", "confluence", "jira"],
  connections: { bitbucket: [], confluence: [], jira: ["jira.corp.example:8443"] },
};
const REFUSED = {
  detail: { state: "private_host_entry_refused", reason: "entry_not_private", entry_index: 1 },
};

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jiraDraft() {
  return draftsFromPayload(LISTED).find((draft) => draft.connection === "jira");
}

test("the listing becomes one clean draft per allowlistable type, in server order", () => {
  const drafts = draftsFromPayload(LISTED);
  assert.deepEqual(drafts.map((draft) => draft.connection), ["bitbucket", "confluence", "jira"]);
  assert.deepEqual(entriesOf(drafts[2]), ["jira.corp.example:8443"]);
  assert.equal(drafts[2].dirty, false);
  assert.deepEqual(draftsFromPayload({ allowlistable: ["Jira <b>", 7] }), []);
  assert.deepEqual(draftsFromPayload(null), []);
});

test("the client shape check uses the server codes and requires the port", () => {
  assert.equal(entryShapeRefusal("jira.corp.example:8443"), null);
  assert.equal(entryShapeRefusal("10.20.0.5:443"), null);
  assert.equal(entryShapeRefusal("[fd12::5]:443"), null);
  assert.equal(entryShapeRefusal("jira.corp.example"), "entry_port_required");
  assert.equal(entryShapeRefusal("fd12::5"), "entry_malformed");
  assert.equal(entryShapeRefusal("host:70000"), "entry_malformed");
  assert.equal(entryShapeRefusal("host:0"), "entry_malformed");
});

test("adding normalizes, refuses duplicates, and removing marks the draft unsaved", () => {
  const added = addEntry(jiraDraft(), "  10.20.0.5:443 ");
  assert.equal(added.ok, true);
  assert.deepEqual(entriesOf(added.draft), ["jira.corp.example:8443", "10.20.0.5:443"]);
  assert.equal(added.draft.dirty, true);
  assert.deepEqual(addEntry(added.draft, "JIRA.corp.example:8443"), { ok: false, reason: "entry_duplicate" });
  const removed = removeEntry(added.draft, added.draft.rows[0].key);
  assert.deepEqual(entriesOf(removed), ["10.20.0.5:443"]);
});

test("a refusal marks only the entry at entry_index, with the code and never free text", () => {
  const draft = addEntry(jiraDraft(), "8.8.8.8:443").draft;
  const refusal = parsePrivateHostRefusal(400, REFUSED);
  assert.deepEqual(refusal, { reason: "entry_not_private", entryIndex: 1 });
  const marked = applyRefusal(draft, refusal);
  assert.deepEqual(marked.rows.map((row) => row.refusal), [null, "entry_not_private"]);
  assert.equal(marked.listRefusal, null);
  assert.deepEqual(entriesOf(marked), entriesOf(draft), "the unsaved list is kept");
  assert.equal(marked.dirty, true);

  const hostile = parsePrivateHostRefusal(400, {
    detail: { state: "private_host_entry_refused", reason: "Refused http://10.0.0.1 secret", entry_index: "1" },
  });
  assert.deepEqual(hostile, { reason: "request_refused", entryIndex: null });
  assert.equal(applyRefusal(draft, hostile).listRefusal, "request_refused");
  assert.equal(parsePrivateHostRefusal(409, REFUSED), null);
  assert.equal(parsePrivateHostRefusal(400, { detail: "entry_malformed" }), null);
});

test("a failed load reports the fixed state code or the HTTP status only", () => {
  assert.equal(loadFailureCode(409, { detail: { state: "private_host_allowlist_unavailable" } }), "private_host_allowlist_unavailable");
  assert.equal(loadFailureCode(403, { error: "Forbidden: origin https://evil.example" }), "http_403");
});

test("saving PUTs the full list of one type and returns the refusal on 400", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(REFUSED), { status: 400, headers: { "Content-Type": "application/json" } });
  };
  const outcome = await savePrivateHostEntries("jira", ["jira.corp.example:8443", "8.8.8.8:443"]);
  assert.deepEqual(outcome, { ok: false, refusal: { reason: "entry_not_private", entryIndex: 1 } });
  assert.equal(calls[0].url, `${PRIVATE_HOSTS_PATH}/jira`);
  assert.equal(calls[0].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].init.body), { entries: ["jira.corp.example:8443", "8.8.8.8:443"] });

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ connection: "jira", entries: ["10.20.0.5:443"] }), { status: 200 });
  assert.deepEqual(await savePrivateHostEntries("jira", ["10.20.0.5:443"]), { ok: true, entries: ["10.20.0.5:443"] });
});
