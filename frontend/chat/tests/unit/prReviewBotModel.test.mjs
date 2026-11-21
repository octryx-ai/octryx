import assert from "node:assert/strict";
import test from "node:test";

import { botControls, botLoadProblem, botSaveErrors, botSettingsBody, botSettingsProblems, branchProblem, hasBotErrors, OFF_SETTINGS, providerLabel, readBotPayload, readBotRepository, readBotSaved, skippedText, sameBotSettings, syncErrorText, syncResultText, webhookLine } from "../../src/admin/components/projectsTab/repositories/prReviewBotModel.ts";
import { STATUS_OPTIONS, GATE_HINT } from "../../src/admin/components/projectsTab/repositories/prReviewBotTexts.ts";
import { limitProblem, parseLimit } from "../../src/admin/components/projectsTab/repositories/prReviewBotLimits.ts";

const row = (settings) => ({ id: "r1", name: "acme/pay", repository: "github:acme/pay", settings });

test("the GET payload: rows with their settings, the server's triggers in the UI order, can_edit and the webhook", () => {
  const payload = readBotPayload({
    repositories: [row({ trigger: "both", protected_branches: ["main", " main ", "release"], review_drafts: true }), { name: "no id" }],
    triggers: ["webhook", "sync", "both", "off", "hourly"],
    can_edit: true,
    webhook_configured: true,
  });
  assert.equal(payload.repositories.length, 1);
  assert.deepEqual(payload.repositories[0].settings,
    { trigger: "both", protectedBranches: ["main", "release"], reviewDrafts: true, statusPolicy: "inform", fixRuns: false,
      sizeLimitLines: 800, sizeLimitFiles: 25, hotspotPaths: [], kept: {} });
  assert.deepEqual(payload.triggers, ["off", "webhook", "sync", "both"]);
  assert.equal(payload.canEdit, true);
  assert.equal(payload.webhookConfigured, true);
});

test("a member's payload is read-only; missing or unknown values fall back to off", () => {
  const payload = readBotPayload({ repositories: [row({ trigger: "weekly" }), row(null)], triggers: ["sync", "off"] });
  assert.equal(payload.canEdit, false);
  assert.equal(payload.webhookConfigured, false);
  assert.deepEqual(payload.triggers, ["off", "sync"]);
  assert.deepEqual(payload.repositories.map((item) => item.settings), [OFF_SETTINGS, OFF_SETTINGS]);
  const controls = botControls(false, payload.repositories[0].settings, false, false);
  assert.equal(controls.disabled, true);
  assert.equal(controls.showSave, false);
  assert.equal(controls.showSync, false);
  assert.match(controls.readOnlyNote, /Workspace admin or owner/);
});

test("the PUT body carries every field, the edited and the kept ones, because the PUT replaces the whole object", () => {
  const limits = { fix_runs: false, size_limit_lines: 800, size_limit_files: 25, hotspot_paths: [] };
  assert.deepEqual(botSettingsBody(OFF_SETTINGS),
    { trigger: "off", protected_branches: [], review_drafts: false, status_policy: "inform", ...limits });
  assert.deepEqual(botSettingsBody({ ...OFF_SETTINGS, trigger: "sync", protectedBranches: [" main"], reviewDrafts: true }),
    { trigger: "sync", protected_branches: ["main"], review_drafts: true, status_policy: "inform", ...limits });
  const saved = readBotRepository({ ...row({ trigger: "sync", protected_branches: ["main"], review_drafts: true }), can_edit: true });
  assert.ok(sameBotSettings(saved.settings, { ...OFF_SETTINGS, trigger: "sync", protectedBranches: ["main"], reviewDrafts: true }));
});

test("settings this panel does not edit go back unchanged; fix runs and the size brake are read and sent", () => {
  const stored = readBotRepository(row({ trigger: "both", fix_runs: true, size_limit_lines: 1200, status_policy: "gate",
    future_setting: "x" }));
  assert.equal(stored.settings.statusPolicy, "gate");
  assert.equal(stored.settings.fixRuns, true);
  const body = botSettingsBody({ ...stored.settings, reviewDrafts: true });
  assert.deepEqual(body, { future_setting: "x", trigger: "both", protected_branches: [], review_drafts: true,
    status_policy: "gate", fix_runs: true, size_limit_lines: 1200, size_limit_files: 25, hotspot_paths: [] });
});

test("the size brake takes whole numbers from 1 to 100000 and hotspot globs follow the server's rules", () => {
  assert.equal(readBotRepository(row({ trigger: "sync", size_limit_files: 0, size_limit_lines: 2.5 })).settings.sizeLimitFiles, 25,
    "an out-of-range stored value reads as the default");
  assert.equal(parseLimit(" 1200 "), 1200);
  assert.ok(Number.isNaN(parseLimit("12a")));
  assert.equal(limitProblem(1), null);
  assert.equal(limitProblem(100000), null);
  assert.match(limitProblem(0), /1 to 100,000/);
  assert.match(limitProblem(Number.NaN), /whole number/);
  const draft = { ...OFF_SETTINGS, sizeLimitLines: 0, hotspotPaths: ["src/payments/**", " ", "src/payments/**"] };
  const problems = botSettingsProblems(draft);
  assert.match(problems.sizeLimitLines, /whole number/);
  assert.deepEqual(Object.keys(problems.hotspots), [" ", "src/payments/**"]);
  assert.ok(hasBotErrors(problems));
  assert.match(botSettingsProblems({ ...OFF_SETTINGS, hotspotPaths: Array.from({ length: 51 }, (_, i) => `p${i}/**`) })
    .hotspotPaths, /At most 50/);
  assert.ok(!hasBotErrors(botSettingsProblems({ ...OFF_SETTINGS, hotspotPaths: ["src/payments/**"] })));
});

test("the server's refusals of these fields land at the field", () => {
  const sent = OFF_SETTINGS;
  assert.ok(botSaveErrors(422, { state: "denied", reason: "size_limit_invalid", path: "size_limit_files" }, sent).sizeLimitFiles);
  assert.ok(botSaveErrors(422, { state: "denied", reason: "size_limit_invalid", path: "size_limit_lines" }, sent).sizeLimitLines);
  assert.match(botSaveErrors(422, { state: "denied", reason: "hotspot_paths_invalid", path: "hotspot_paths" }, sent).hotspotPaths,
    /at most 50/);
});

test("the status policy defaults to inform, an unknown one reads as inform, and the server's refusal lands at the field", () => {
  assert.equal(readBotRepository(row({ trigger: "sync" })).settings.statusPolicy, "inform");
  assert.equal(readBotRepository(row({ trigger: "sync", status_policy: "block" })).settings.statusPolicy, "inform");
  const gate = { ...OFF_SETTINGS, statusPolicy: "gate" };
  assert.ok(!sameBotSettings(gate, OFF_SETTINGS), "changing only the status policy offers Save");
  assert.match(botSaveErrors(400, { state: "denied", reason: "status_policy_unknown", path: "status_policy" }, gate).statusPolicy,
    /does not know this choice/);
  assert.ok(STATUS_OPTIONS.inform.recommended && !STATUS_OPTIONS.gate.recommended);
  assert.match(GATE_HINT, /branch protection/);
});

test("branch names follow the server's rules: empty, too long, whitespace, '..', listed twice", () => {
  assert.equal(branchProblem("main", []), null);
  assert.equal(branchProblem("feature/a.b", []), null);
  assert.match(branchProblem("  ", []), /empty/);
  assert.match(branchProblem("x".repeat(256), []), /255/);
  assert.equal(branchProblem("x".repeat(255), []), null);
  assert.match(branchProblem("my branch", []), /spaces/);
  assert.match(branchProblem("a..b", []), /\.\./);
  assert.match(branchProblem("main", ["main"]), /twice/);
  const problems = botSettingsProblems({ ...OFF_SETTINGS, trigger: "both", protectedBranches: ["main", "my branch", "main"] });
  assert.deepEqual(Object.keys(problems.branches), ["my branch", "main"]);
  assert.ok(hasBotErrors(problems));
  assert.ok(!hasBotErrors(botSettingsProblems({ ...OFF_SETTINGS, protectedBranches: ["main", "release/1.x"] })));
});

test("each refusal reason lands at its field; protected_branch_invalid at the chip its path names", () => {
  const sent = { trigger: "both", protectedBranches: ["main", "a..b"], reviewDrafts: false };
  const chip = botSaveErrors(400, { state: "denied", reason: "protected_branch_invalid", path: "protected_branches[1]" }, sent);
  assert.deepEqual(Object.keys(chip.branches), ["a..b"]);
  assert.match(chip.branches["a..b"], /\.\./);
  assert.ok(botSaveErrors(400, { reason: "protected_branch_invalid" }, sent).protectedBranches);
  assert.ok(botSaveErrors(400, { reason: "protected_branches_not_a_list" }, sent).protectedBranches);
  assert.ok(botSaveErrors(400, { reason: "trigger_unknown" }, sent).trigger);
  assert.match(botSaveErrors(400, { reason: "settings_not_an_object" }, sent).general, /as a whole/);
  assert.match(botSaveErrors(403, { reason: "workspace_admin_required" }, sent).general, /admin or owner/);
  assert.match(botSaveErrors(404, { reason: "repository_not_found" }, sent).general, /no longer in the Workspace/);
  assert.match(botSaveErrors(404, { reason: "workspace_not_found" }, sent).general, /Workspace no longer exists/);
  assert.match(botSaveErrors(0, null, sent).general, /did not reach/);
});

test("a server without the review bot hides the section; a missing Workspace is said in words", () => {
  assert.deepEqual(botLoadProblem(404, { detail: "Not Found" }), { kind: "unavailable" });
  assert.match(botLoadProblem(404, { state: "denied", reason: "workspace_not_found" }).text, /no longer exists/);
  assert.equal(botLoadProblem(500, null).kind, "error");
});

test("the webhook line is a problem only when the chosen trigger needs a webhook the Workspace lacks", () => {
  assert.deepEqual(webhookLine("both", false), { tone: "problem", text: "No pull request webhook in this Workspace yet: Admin → Webhooks." });
  assert.equal(webhookLine("webhook", false).tone, "problem");
  assert.equal(webhookLine("sync", false).tone, "quiet");
  assert.match(webhookLine("webhook", true).text, /is set up/);
});

test("Sync now: admins only, on a saved sync or both trigger", () => {
  const both = { ...OFF_SETTINGS, trigger: "both" };
  assert.equal(botControls(true, both, false, false).syncDisabled, false);
  assert.equal(botControls(true, { ...OFF_SETTINGS, trigger: "sync" }, false, false).syncDisabled, false);
  assert.equal(botControls(true, { ...OFF_SETTINGS, trigger: "webhook" }, false, false).syncDisabled, true);
  assert.equal(botControls(true, OFF_SETTINGS, false, false).syncDisabled, true);
  const unsaved = botControls(true, both, true, false);
  assert.equal(unsaved.syncDisabled, true);
  assert.match(unsaved.syncHint, /Save first/);
  assert.equal(botControls(true, both, false, true).syncDisabled, true);
});

test("the PUT's answer carries the Workspace's webhook state; without it the GET's value stays", () => {
  const answer = { ...row({ trigger: "both" }), can_edit: true, webhook_configured: true };
  assert.equal(readBotSaved(answer).webhookConfigured, true);
  assert.equal(readBotSaved({ ...answer, webhook_configured: false }).webhookConfigured, false);
  assert.equal(readBotSaved(row({ trigger: "both" })).webhookConfigured, null);
  assert.equal(readBotSaved({ name: "no id" }), null);
});

test("skipped heads are counted per reason in words; an unknown reason shows by its key", () => {
  assert.equal(skippedText(3, { draft: 1, fork: 2 }), "Skipped 3: 1 draft (review drafts is off), 2 from forks (not reviewed yet).");
  assert.equal(skippedText(1, { no_head: 1 }), "Skipped 1: 1 without a head commit (the provider named none).");
  assert.equal(skippedText(2, { fork: 1, bot_off: 1 }), "Skipped 2: 1 from a fork (not reviewed yet), 1 bot_off.");
  assert.equal(skippedText(4, { draft: 2 }), "Skipped 4: 2 drafts (review drafts is off), 2 other.");
  assert.equal(skippedText(2, {}), "Skipped 2.");
});

test("the sync's answer and refusals in words", () => {
  assert.equal(syncResultText({ repository: "github:acme/pay", outcomes: { started: 2, already_reviewed: 1, skipped: 3 },
    skipped_reasons: { draft: 1, fork: 2 } }),
    "Synced: 2 reviews started, 1 pull request was already reviewed at this commit. "
    + "Skipped 3: 1 draft (review drafts is off), 2 from forks (not reviewed yet).");
  assert.equal(syncResultText({ outcomes: { already_reviewed: 2 } }), "Synced: 2 pull requests were already reviewed at this commit.");
  assert.equal(syncResultText({ outcomes: { skipped: 1 }, skipped_reasons: { draft: 1 } }), "Synced. Skipped 1: 1 draft (review drafts is off).");
  assert.equal(syncResultText({ outcomes: { started: 0, already_reviewed: 0, skipped: 0 } }), "Synced: no open pull request.");
  assert.match(syncErrorText(409, { reason: "sync_not_switched_on" }), /save first/);
  assert.equal(syncErrorText(502, { reason: "pull_requests_unreadable: 401 bad credentials" }),
    "Not synced: the provider refused to list the pull requests (401 bad credentials).");
  assert.match(syncErrorText(403, { reason: "workspace_admin_required" }), /admin or owner/);
  assert.match(syncErrorText(404, { reason: "workspace_not_found" }), /Workspace no longer exists/);
  assert.match(syncErrorText(404, { reason: "repository_not_found" }), /no longer in the Workspace/);
  assert.match(syncErrorText(0, null), /did not reach/);
});

test("each repository card names its platform, GitLab included; an unknown one stays unnamed", () => {
  assert.deepEqual(["github:acme/pay", "gitlab:group/sub/pay", "Bitbucket:P/r", "svn:x/y"].map(providerLabel),
    ["GitHub", "GitLab", "Bitbucket", ""]);
});
