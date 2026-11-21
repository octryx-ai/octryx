// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorPresenters.test.mjs
//
// The connector catalog is alphabetical with the
// preset's own secret fields, and the private-host allowlist shows a form only
// for connection types that are configured, already have entries, or were
// opened explicitly. Neither changes stored data.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  connectorCredentialSummary,
  sortConnectorCatalog,
} from "../../src/admin/components/connectorsTab/connectorCatalog.ts";
import {
  draftFromEntries,
  partitionAllowlistDrafts,
} from "../../src/admin/components/connectorsTab/privateHostAllowlistModel.ts";

describe("connector catalog", () => {
  test("sorted by label, case-insensitive", () => {
    const sorted = sortConnectorCatalog([
      { tool_name: "jira", label: "Jira" },
      { tool_name: "argocd", label: "argo CD" },
      { tool_name: "bitbucket", label: "Bitbucket" },
    ]);
    assert.deepEqual(sorted.map((item) => item.tool_name), ["argocd", "bitbucket", "jira"]);
  });

  test("credential line comes from secret_fields only", () => {
    assert.equal(
      connectorCredentialSummary({ tool_name: "jira", label: "Jira", secret_fields: ["jira_token", "jira_password"] }),
      "Secrets: token, password",
    );
    assert.equal(connectorCredentialSummary({ tool_name: "loki", label: "Loki", secret_fields: [] }), "No stored secret");
  });
});

describe("private host allowlist visibility", () => {
  const drafts = [
    draftFromEntries("jira", []),
    draftFromEntries("confluence", ["10.0.0.5:443"]),
    draftFromEntries("gitlab", []),
    draftFromEntries("sonarqube", []),
  ];

  test("configured, non-empty or opened types are shown; the rest stay reachable", () => {
    const { shown, hidden } = partitionAllowlistDrafts(drafts, ["jira"], ["sonarqube"]);
    assert.deepEqual(shown.map((draft) => draft.connection), ["jira", "confluence", "sonarqube"]);
    assert.deepEqual(hidden.map((draft) => draft.connection), ["gitlab"]);
  });

  test("zero connectors and zero entries show no form at all", () => {
    const empty = drafts.filter((draft) => draft.saved.length === 0);
    const { shown, hidden } = partitionAllowlistDrafts(empty, [], []);
    assert.equal(shown.length, 0);
    assert.equal(hidden.length, 3);
  });
});
