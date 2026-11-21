// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/linkedAccounts.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canFindByEmail,
  canVerify,
  linkedAccountErrorText,
  platformRows,
  readLinkedAccounts,
  verificationBadge,
} from "../../src/chat/profile/linkedAccountsModel.ts";
import { readPersonalTab } from "../../src/chat/devices/personalSettingsTab.ts";

const ANSWER = {
  user: { id: "u1", username: "dev", display_name: "Dev" },
  accounts: [{
    platform: "atlassian", label: "Atlassian Cloud", identifier_kind: "account_id", identifier: "557058:abc",
    display_name: "Dev Person", verification_status: "verified", verified_at: "2026-10-10T18:00:00",
    verification: { detail: "Atlassian Cloud knows this account", via: "search_jira_users" }, source: "self",
  }, { platform: "", identifier: "dropped" }],
  platforms: [
    { platform: "atlassian", label: "Atlassian Cloud", identifier_kind: "account_id", description: "Atlassian" },
    { platform: "github", label: "GitHub", identifier_kind: "username", description: "GitHub login" },
  ],
  workspaces: [{ id: "w1", name: "Payments" }],
};

test("the linked accounts answer becomes one row per platform", () => {
  const data = readLinkedAccounts(ANSWER);
  assert.equal(data.accounts.length, 1);
  const rows = platformRows(data);
  assert.deepEqual(rows.map((row) => [row.platform.platform, row.account?.identifier ?? null]),
    [["atlassian", "557058:abc"], ["github", null]]);
  assert.equal(rows[0].account.verificationDetail, "Atlassian Cloud knows this account");
  assert.deepEqual(data.workspaces, [{ id: "w1", name: "Payments" }]);
  assert.equal(readLinkedAccounts({ accounts: "x" }), null);
});

test("verification is offered where a connection can check, email lookup only for Atlassian", () => {
  assert.deepEqual(["atlassian", "jira_server", "bitbucket_server", "github", "gitlab"].map(canVerify),
    [true, true, true, false, false]);
  assert.deepEqual(["atlassian", "github"].map(canFindByEmail), [true, false]);
  const account = readLinkedAccounts(ANSWER).accounts[0];
  assert.deepEqual(verificationBadge(account), { label: "Verified", tone: "active" });
  assert.equal(verificationBadge({ ...account, verificationStatus: "failed" }).tone, "danger");
  assert.equal(verificationBadge({ ...account, verificationStatus: "unverified" }).label, "Unverified");
});

test("refusals read as text; a run card link opens Profile", () => {
  assert.equal(linkedAccountErrorText({ code: "not_your_account" }), "You can change only your own linked accounts.");
  assert.equal(linkedAccountErrorText({ code: "needs_configuration", detail: "No Jira Cloud connection." }),
    "No Jira Cloud connection.");
  assert.equal(linkedAccountErrorText(new Error("x")), "The linked account could not be saved.");
  assert.equal(readPersonalTab("?area=personal&tab=profile"), "profile");
  assert.equal(readPersonalTab("?area=personal"), "devices");
  assert.equal(readPersonalTab("?area=personal&tab=notifications"), "notifications");
  assert.equal(readPersonalTab("?area=personal&tab=unknown"), "devices");
  assert.equal(readPersonalTab("?tab=profile"), "devices");
});
