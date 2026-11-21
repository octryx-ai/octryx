// The run's documentation events (auto_pages.py) as history lines: the written page links out, a skip says its
// reason in words and links the Documentation target card, a failure says its reason.
import assert from "node:assert/strict";
import { test } from "node:test";

import { documentationReasonText } from "../../src/chat/workflowRun/documentationEventsModel.ts";
import { runHistory } from "../../src/chat/workflowRun/runHistoryModel.ts";

const event = (id, kind, detail) => ({ id, kind, node_id: "docs", detail, actor_id: null, created_at: null });

test("documentation events become readable history lines with their links", () => {
  const entries = runHistory([
    event("1", "documentation_page_written", { slot: "spec", title: "OCX-7: Coffee - Specification", url: "https://acme.atlassian.net/wiki/x/1", page_id: "1" }),
    event("2", "documentation_skipped", { reason: "no_parent_page" }),
    event("3", "documentation_failed", { slot: "overview", title: "OCX-7", reason: "Confluence answered 503" }),
    event("4", "documentation_grant_recorded", { grant_id: "g" }),
  ], [], () => "", null, "ws 1");
  assert.equal(entries.length, 3);
  assert.deepEqual([entries[0].title, entries[0].text, entries[0].link], ["Page written", "OCX-7: Coffee - Specification",
    { href: "https://acme.atlassian.net/wiki/x/1", label: "Open page", external: true }]);
  assert.equal(entries[1].text, "no parent page set in Documentation target");
  assert.equal(entries[1].link.href, "/chat?area=admin&tab=projects&workspace_id=ws+1&section=documentation");
  assert.deepEqual([entries[2].title, entries[2].text, entries[2].link], ["Documentation failed", "Confluence answered 503", undefined]);
});

test("a page url that is not http(s) is not linked; a skip the card cannot fix has no card link", () => {
  const [page, skip] = runHistory([
    event("1", "documentation_page_written", { title: "T", url: "javascript:alert(1)" }),
    event("2", "documentation_skipped", { reason: "spec_unavailable" }),
  ], [], () => "", null, "ws");
  assert.equal(page.link, undefined);
  assert.equal(skip.link, undefined);
  assert.equal(skip.text, "the specification of this commit could not be read");
  assert.equal(documentationReasonText("some_new_code"), "some new code");
});
