// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectionToolLabels.test.mjs
// The Agent tools tab of a connection listed raw function names (add_bitbucket_pull_request_comment).
// It shows them in words, without the connection's own type, and keeps the read/write level.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { connectionToolLabel } from "../../src/admin/components/connections/connectionsModel.ts";

test("a tool name in words, without the connection type", () => {
  assert.equal(connectionToolLabel("add_bitbucket_pull_request_comment", "bitbucket"), "Add pull request comment");
  assert.equal(connectionToolLabel("list_recent_bitbucket_commits", "bitbucket"), "List recent commits");
  assert.equal(connectionToolLabel("commit_and_push_repository_branch", "bitbucket"), "Commit and push repository branch");
  assert.equal(connectionToolLabel("search_jira_tickets", "jira"), "Search tickets");
  assert.equal(connectionToolLabel("get_pr_url", "github"), "Get PR URL");
  assert.equal(connectionToolLabel("bitbucket", "bitbucket"), "bitbucket", "never empty");
});

test("the Agent tools tab shows the words, the function name as tooltip and the level", () => {
  const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin/components/connections/ConnectionUseTabs.tsx");
  const source = fs.readFileSync(SRC, "utf8");
  assert.match(source, /<span title=\{tool\.name\}>\{connectionToolLabel\(tool\.name, detail\.type\)\}<\/span>/);
  assert.match(source, /tool\.level === "write" \? "Writes" : tool\.level === "read" \? "Reads"/);
});
