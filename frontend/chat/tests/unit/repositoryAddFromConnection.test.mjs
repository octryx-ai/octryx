// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/repositoryAddFromConnection.test.mjs
//
// "ich kann immer noch keine Bitbucket repo registrieren". A repository from a connection is added in
// Knowledge › Sources › Add source › Git repository › From a connection; the Repositories page, a connection's
// Repositories tab and Settings › Repositories now link there directly, with the connection preselected.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  addRepositoryFromConnectionHref,
  requestedAddSource,
} from "../../src/admin/components/workspaceKnowledge/sourceLinks.ts";

test("the link opens Add source on a git repository from that connection", () => {
  const href = addRepositoryFromConnectionHref("ws-1", "b954");
  assert.match(
    href,
    /workspace_id=ws-1&source=new&kind=git_repository&from=connection&connection=b954$/,
  );
  const asked = requestedAddSource(href.slice(href.indexOf("?")));
  assert.deepEqual(asked, {
    kind: "git_repository",
    fromConnection: true,
    connectionId: "b954",
  });
  assert.match(
    addRepositoryFromConnectionHref(""),
    /^\/chat\?area=knowledge&tab=workspaceKnowledge&source=new&kind=/,
  );
  assert.deepEqual(requestedAddSource("?source=new"), {
    kind: "",
    fromConnection: false,
    connectionId: "",
  });
});

test("the Repositories page keeps its add action when repositories exist", () => {
  const page = readFileSync(
    new URL(
      "../../src/chat/coding/repository/RepositoryPage.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const overview = page.slice(
    page.indexOf("export function RepositoryOverview"),
  );
  assert.ok(
    overview.indexOf('data-testid="repository-add"') >
      overview.indexOf("if (!rows.length)"),
  );
});
