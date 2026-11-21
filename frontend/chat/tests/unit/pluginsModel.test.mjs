// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/pluginsModel.test.mjs
// Plugins from the image, switched on per Workspace (plugins contract §6): the presentation model of Workspace ›
// Plugins and Admin › Plugins.
import assert from "node:assert/strict";
import { test } from "node:test";

import { activeWorkspacesText, afterSwitch, availableRow, emptyText, imageReportView, notInstallableText, outcomeText, pluginErrorView } from "../../src/admin/components/plugins/pluginsModel.ts";
import { summaryText } from "../../src/admin/components/plugins/pluginWords.ts";

const item = (over = {}) => ({
  plugin: "octryx.release-notes", name: "Release notes", version: "1.1.0", publisher: "Octryx", description: "…",
  in_image: true, active: false, install_id: null, needs_settings: false,
  summary: [
    { key: "plugins.summary.brings", text: "Brings 1 skill, 1 workflow, 1 role", params: { skills: 1, workflows: 1, roles: 1 } },
    { key: "plugins.summary.pages", text: "Adds pages: Releases", params: { pages: ["Releases"] } },
    { key: "plugins.summary.uses", text: "Uses jira, confluence, github of this Workspace", params: { connections: ["jira", "confluence", "github"] } },
    { key: "plugins.summary.writes", text: "Writes to confluence, asks every time", params: { writes: ["confluence"] } },
  ],
  ...over,
});
const admin = { is_platform_admin: false, can_activate: true };
const member = { is_platform_admin: false, can_activate: false };
const refusal = (status, detail) => Object.assign(new Error(detail.message || "Refused"), { status, code: detail.code, detail });

test("summary lines name connections as people know them; an unknown line keeps the backend's text", () => {
  const lines = availableRow(item(), admin).lines;
  assert.deepEqual(lines, [
    "Brings 1 skill, 1 workflow, 1 role",
    "Adds the page Releases",
    "Uses Jira, Confluence and GitHub of this Workspace",
    "Writes to Confluence, asks every time",
  ]);
  assert.equal(summaryText({ key: "plugins.summary.new_kind", text: "Something new" }), "Something new");
  assert.equal(summaryText({ key: "plugins.summary.uses", text: "Uses x", params: {} }), "Uses x", "no params: the backend's text");
  const many = Array.from({ length: 7 }, (_, n) => ({ key: "x", text: `line ${n}` }));
  assert.equal(availableRow(item({ summary: many }), admin).lines.length, 5, "at most five lines");
});

test("the switch: admins get it, members read On / Off, a plugin missing from the image is greyed without it", () => {
  assert.equal(availableRow(item(), admin).switchable, true);
  assert.equal(availableRow(item(), member).switchable, false);
  assert.equal(availableRow(item(), null).switchable, false, "no viewer (Admin list): no switch");
  const missing = availableRow(item({ in_image: false, active: true, install_id: "i1" }), admin);
  assert.deepEqual([missing.missing, missing.switchable, missing.on, missing.canOpen], [true, false, false, false]);
});

test("an active row opens its detail; needs settings only while it is on", () => {
  const on = availableRow(item({ active: true, install_id: "i1", needs_settings: true }), admin);
  assert.deepEqual([on.on, on.canOpen, on.needsSettings], [true, true, true]);
  const off = availableRow(item({ active: false, install_id: "i1", needs_settings: true }), admin);
  assert.deepEqual([off.on, off.canOpen, off.needsSettings], [false, false, false]);
  assert.deepEqual(afterSwitch(item(), { id: "i1", status: "active" }).install_id, "i1");
  assert.equal(afterSwitch(item({ active: true }), { id: "i1", status: "disabled" }).active, false);
});

test("refusals of the switch read in words; the 409 names what is in the way in one sentence", () => {
  const blocked = pluginErrorView(refusal(409, { code: "plugin_not_installable", message: "…", conflicts: [
    { kind: "workflow", key: "release-notes", code: "workflow_key_taken", message: "…" },
    { kind: "role", key: "release_manager", code: "role_key_taken", message: "…" },
  ] }));
  assert.equal(blocked.text,
    "Not switched on: this Workspace already has the workflow release-notes and the role release_manager, which the plugin would bring too.");
  assert.match(notInstallableText([]), /already exists in this Workspace/);
  assert.equal(pluginErrorView(refusal(404, { code: "plugin_not_available", message: "x" })).text, "This plugin is no longer in the Octryx image.");
  assert.deepEqual(pluginErrorView(refusal(403, { code: "plugin_workspace_admin_only", message: "A Workspace admin or owner installs plugins here." })),
    { kind: "forbidden", text: "A Workspace admin or owner installs plugins here." });
  assert.equal(pluginErrorView(new Error("Network down")).text, "Network down");
});

test("the empty list says how a plugin gets here; the folder only when known", () => {
  assert.equal(emptyText("/opt/octryx/plugins"),
    "No plugins yet. An administrator adds a plugin by putting it into the image's plugin folder (/opt/octryx/plugins); it then appears here.");
  assert.doesNotMatch(emptyText(null), /\(/);
});

test("the image folder's last start: the new outcomes in words and failed entries with their reason; Workspaces it is on in, live", () => {
  const report = { folder: "/opt/octryx/plugins", folder_exists: true, started_at: "2026-11-14T09:00:00+00:00", entries: [
    { entry: "release-notes", outcome: "upgraded", plugin: "octryx.release-notes", version: "1.1.0", workspaces: 2 },
    { entry: "code-owners", outcome: "available", plugin: "octryx.code-owners", version: "1.0.0", workspaces: 0 },
    { entry: "incident", outcome: "disabled", plugin: "acme.incident", version: "0.4.0", code: "missing_from_image" },
    { entry: "broken.zip", outcome: "failed", code: "plugin_package_invalid", message: "The package is not valid.",
      issues: [{ code: "x", message: "'publisher' is required.", path: "publisher" }] },
  ] };
  const view = imageReportView(report);
  assert.equal(view.counts, "1 plugin new and available · 1 plugin upgraded · 1 plugin no longer in the image and switched off · 1 plugin failed");
  assert.deepEqual(view.failed.map((entry) => [entry.reason, entry.message, entry.items]),
    [["The package is not valid", "", ["'publisher' is required. (publisher)"]]]);
  assert.equal(outcomeText("enabled"), "back in the image and switched on again");
  assert.deepEqual([activeWorkspacesText(2), activeWorkspacesText(1), activeWorkspacesText(0), activeWorkspacesText(undefined)],
    ["On in 2 Workspaces", "On in 1 Workspace", "Not on in any Workspace", ""]);
  assert.equal(imageReportView({ ...report, entries: [], folder_exists: false }).emptyText, "No plugin folder in this image; nothing was changed.");
});
