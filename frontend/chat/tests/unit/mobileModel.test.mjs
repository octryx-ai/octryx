// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/mobileModel.test.mjs
//
// Octryx Mobile: the Home Screen app's pure parts: the hand-over address, the typed claim code,
// the chats on the person's Macs, the billing choices (API = governed, Seat = seat; only what the Mac has set up and
// the Workspace allows) and the usage line (the tighter seat window, the API budget, a warning from 80 %).
import assert from "node:assert/strict";
import { test } from "node:test";
import { PAGE_CSP, pageSrcDoc } from "../../src/mobile/pagePolicy.ts";
import { fitInside, MAX_PICTURES } from "../../src/mobile/pictures.ts";
import { applicationServerKey, pushSupport } from "../../src/mobile/mobilePush.ts";
import { knownSeqs, mergeJobs, partialJobIds, isFork, takeOverTarget, billingLabel, billingOptions, deviceThreads, folderName, formatClaimInput, parseHash, readLocalSessions } from "../../src/mobile/mobileDeviceChats.ts";
import { groupSteps, groupSummary, shortStep, liveStatusText, mergeProgress, progressSteps, readLiveProgress } from "../../src/mobile/mobileLiveProgress.ts";
import { readStartable, suggestWorkflow, readResponsible, responsibleText, runRefusalText, planStatusLabel, readTaskDetail, readTaskPlan, sourceLabel, nextOffset, readTaskCounts, stateLabel, readCases } from "../../src/mobile/mobileTasksModel.ts";
import { liveDeliveryLabel, readLiveMessage } from "../../src/mobile/mobileLiveSessions.ts";
import { claudeArtifacts, macFileKind, serverArtifacts } from "../../src/mobile/mobileFilesArtifacts.ts";
import { readUsage, shortTime, usageText } from "../../src/mobile/mobileUsageModel.ts";

test("the hand-over address carries the claim in the fragment", () => {
  assert.deepEqual(parseHash("#claim=K7Q4-XM9P"), { claim: "K7Q4-XM9P" });
  assert.deepEqual(parseHash("#c=abc&x=1"), { c: "abc", x: "1" });
  assert.deepEqual(parseHash(""), {});
});

test("a typed claim code is normalized as it is typed", () => {
  assert.equal(formatClaimInput("k7q4"), "K7Q4");
  assert.equal(formatClaimInput("k7q4xm9p"), "K7Q4-XM9P");
  assert.equal(formatClaimInput("k7q4 - xm9p-extra"), "K7Q4-XM9P");
});

test("only chats that run on a Mac are listed, newest first, with their Workspace", () => {
  const groups = [
    { projectId: "ws-1", projectName: "Acme Orders", sessions: [
      { id: "a", title: "Server chat", executionTarget: null, lastActivityAt: "2026-11-07T10:00:00Z" },
      { id: "b", title: "Older", executionTarget: { kind: "device", deviceName: "MacBook" }, lastActivityAt: "2026-11-07T09:00:00Z" },
    ] },
    { projectId: "ws-2", projectName: "Alpha", sessions: [
      { id: "c", title: "Newer", executionTarget: { kind: "device", deviceName: "MacBook" }, lastActivityAt: "2026-11-07T11:00:00Z" },
    ] },
  ];
  assert.deepEqual(deviceThreads(groups).map((thread) => [thread.id, thread.projectId]), [["c", "ws-2"], ["b", "ws-1"]]);
  assert.deepEqual(deviceThreads(null), []);
});

test("billing offers only what the Mac has and the Workspace allows", () => {
  const device = { profiles: ["governed", "seat"], seatLogin: true };
  const policy = { enabled: true, platformEnabled: true, allowedProfiles: ["governed", "seat"], seatAllowed: true };
  assert.deepEqual(billingOptions(device, policy), ["governed", "seat"]);
  assert.deepEqual(billingOptions({ ...device, seatLogin: false }, policy), ["governed"]);
  assert.deepEqual(billingOptions(device, { ...policy, seatAllowed: false }), ["governed"]);
  assert.deepEqual(billingOptions(device, { ...policy, allowedProfiles: ["seat"] }), ["seat"]);
  assert.deepEqual(billingOptions(device, { ...policy, enabled: false }), []);
  assert.deepEqual(billingOptions(null, policy), []);
  assert.equal(billingLabel("seat"), "Own subscription");
  assert.equal(billingLabel("governed"), "Company model");
});

test("the usage line shows the tighter seat window and the API budget, warning from 80 %", () => {
  const usage = readUsage({ spent_usd: 12.4, limit_usd: 50, seat_allowance: {
    five_hour_pct: 95.2, five_hour_resets_at: "2026-11-07T14:20:00Z", seven_day_pct: 40, seven_day_resets_at: null } });
  assert.deepEqual(usage.seat, { percent: 95, window: "5h", resetsAt: "2026-11-07T14:20:00Z" });
  assert.equal(usage.warn, true);
  assert.equal(usageText(usage), "Seat 95 % (5h) · API 12 of 50 $ today");
  const quiet = readUsage({ spent_usd: null, limit_usd: null, seat_allowance: { five_hour_pct: 10, seven_day_pct: 30 } });
  assert.equal(usageText(quiet), "Seat 30 % (7d)");
  assert.equal(quiet.warn, false);
  assert.equal(usageText(readUsage(null)), "");
});

test("small labels", () => {
  assert.equal(folderName("/Users/dev/src/acme-orders-api/"), "acme-orders-api");
  const now = Date.parse("2026-11-07T12:00:00Z");
  assert.equal(shortTime("2026-11-07T11:57:00Z", now), "3 min");
  assert.equal(shortTime("2026-11-07T09:00:00Z", now), "3 h");
  assert.equal(shortTime("nonsense", now), "");
});

test("open terminal sessions are read defensively and listed with the Mac chats by recent activity", async () => {
  const { readOpenSessions, homeRows, activityLabel, activityDot } = await import("../../src/mobile/mobileTerminalSessions.ts");
  const sessions = readOpenSessions({ items: [
    { id: "h1", title: "Pricing refactor", workspace: { id: "ws-1", name: "Acme Orders" }, device: "MacBook Pro",
      profile: "seat", activity: "waiting", activity_at: "2026-11-07T11:59:00Z", last_text: "Done.", started_at: "2026-11-07T10:00:00Z" },
    { id: "h2", title: null, work_item: "BRD-6", workspace: {}, activity: "hacking", activity_at: "2026-11-07T11:00:00Z" },
    { title: "no id" },
  ] });
  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].lastText, "Done.");
  assert.equal(sessions[1].title, "BRD-6");
  assert.equal(sessions[1].activity, "working"); // an unknown activity reads as working
  assert.equal(activityLabel("waiting"), "Waiting for you");
  assert.equal(activityLabel("approval"), "Needs your approval");
  assert.equal(activityDot("working"), "m-dot-blue");
  const rows = homeRows(sessions, [{ id: "c", title: "Chat", lastActivityAt: "2026-11-07T11:30:00Z", projectId: "ws-1" }]);
  assert.deepEqual(rows.map((row) => row.kind), ["session", "thread", "session"]);
  assert.deepEqual(readOpenSessions(null), []);
});

test("the VAPID key becomes the bytes pushManager.subscribe wants", () => {
  assert.deepEqual(Array.from(applicationServerKey("BAEC_-8")), [4, 1, 2, 255, 239]);
});

test("push needs the Home Screen app on an iPhone", () => {
  const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)";
  const tab = { matchMedia: () => ({ matches: false }) };
  assert.equal(pushSupport(tab, { serviceWorker: {}, userAgent: iphone }), "home-screen");
  const app = { PushManager: {}, Notification: {}, matchMedia: () => ({ matches: true }) };
  assert.equal(pushSupport(app, { serviceWorker: {}, userAgent: iphone, standalone: true }), "ok");
  assert.equal(pushSupport(tab, { userAgent: "Firefox" }), "unsupported");
});

test("the turn's options are read safely and the code changes come from the job's events", async () => {
  const { readTurnOptions } = await import("../../src/mobile/mobileTurnOptions.ts");
  const { codeChanges } = await import("../../src/mobile/mobileFilesArtifacts.ts");
  assert.deepEqual(readTurnOptions('{"model":"claude-opus-5-5","effort":"high","permissionMode":"bypassPermissions"}'),
    { model: "claude-opus-5-5", effort: "high", permissionMode: "bypassPermissions" });
  assert.deepEqual(readTurnOptions('{"effort":"infinite","permissionMode":"yolo"}'),
    { model: "", effort: "", permissionMode: "" });
  assert.deepEqual(readTurnOptions("not json"), { model: "", effort: "", permissionMode: "" });
  const changes = codeChanges([
    { seq: 4, type: "job_event", body: { kind: "tool_use", tool: "Edit", input_preview: "/repo/a.py", diff: "-a\n+b" } },
    { seq: 5, type: "job_event", body: { kind: "tool_use", tool: "Bash", input_preview: "ls" } },
    { seq: 6, type: "job_event", body: { kind: "text", text: "Done" } },
  ]);
  assert.deepEqual(changes, [{ key: "4", tool: "Edit", file: "/repo/a.py", diff: "-a\n+b" }]);
});

test("a new chat never starts in bypass, and bypass is never kept for new chats", async () => {
  const { initialTurnOptions, turnOptionsToStore } = await import("../../src/mobile/mobileTurnOptions.ts");
  const storage = new Map();
  const getItem = (key) => storage.get(key) ?? null;
  const store = (threadId, options) => turnOptionsToStore(threadId, options).forEach(([k, v]) => storage.set(k, v));
  store("s1", { model: "claude-opus-5-5", effort: "high", permissionMode: "bypassPermissions" });
  assert.deepEqual(initialTurnOptions("s1", getItem),
    { model: "claude-opus-5-5", effort: "high", permissionMode: "bypassPermissions" });  // that chat keeps its mode
  assert.deepEqual(initialTurnOptions(null, getItem), { model: "claude-opus-5-5", effort: "high", permissionMode: "" });
  store(null, { model: "", effort: "max", permissionMode: "bypassPermissions" });  // chosen in New chat
  assert.equal(JSON.parse(storage.get("octryx.mobile.turnOptions:new")).permissionMode, undefined);
  assert.equal(initialTurnOptions(null, getItem).permissionMode, "");
  assert.deepEqual(initialTurnOptions("s2", getItem), { model: "", effort: "max", permissionMode: "" });
});

test("chats on the Server: models, all chats, and a pending answer", async () => {
  const { readRuntimeChoices } = await import("../../src/mobile/mobileTurnOptions.ts");
  const { chatThreads, serverAnswerPending } = await import("../../src/mobile/mobileDeviceChats.ts");
  assert.deepEqual(readRuntimeChoices({ runtimeOptions: [{ value: "", label: "Automatic" },
    { value: "rt-1", label: "Gemma 4", disabledReason: "" }, { value: "rt-2", label: "Opus", disabled: true }, {}] }), [
    { value: "", label: "Automatic", disabled: false }, { value: "rt-1", label: "Gemma 4", disabled: false },
    { value: "rt-2", label: "Opus", disabled: true }]);
  const threads = chatThreads([{ projectId: "ws-1", sessions: [
    { id: "a", title: "on mac", executionTarget: { kind: "device", deviceName: "Mac" }, lastActivityAt: "2026-11-07T10:00:00Z" },
    { id: "b", title: "on server", lastActivityAt: "2026-11-07T11:00:00Z" }] }]);
  assert.deepEqual(threads.map((thread) => [thread.id, thread.onServer]), [["b", true], ["a", false]]);
  const now = Date.parse("2026-11-07T12:00:00Z");
  assert.equal(serverAnswerPending([{ role: "user", createdAt: "2026-11-07T11:59:00Z" }], now), true);
  assert.equal(serverAnswerPending([{ role: "user" }, { role: "assistant" }], now), false);
  assert.equal(serverAnswerPending([{ role: "user", createdAt: "2026-11-07T10:00:00Z" }], now), false);
});

test("Claude Code sessions outside octryx are read safely and labelled by profile", () => {
  const [session] = readLocalSessions({
    items: [
      {
        id: "lcs_1",
        profile: "team",
        title: "",
        folder: "/Users/dev/PRIV",
        folder_name: "PRIV",
        last_text: "Done.",
        updated_at: "2026-11-07T20:00:00Z",
        thread_id: null,
        device: { name: "Alex's Mac", online: true },
        takeover_allowed: true,
      },
      { profile: "x" },
    ],
  });
  assert.equal(session.title, "PRIV");
  assert.equal(session.online, true);
  assert.equal(session.threadId, "");
  assert.equal(session.takeoverAllowed, true);
  assert.equal(billingLabel("local:team"), "Claude Code · team");
  assert.deepEqual(readLocalSessions(null), []);
});

test("live sessions on the Macs are read safely and each message says whether it arrived", async () => {
  const { readLiveSessions, readLiveMessages, liveDeliveryLabel } = await import("../../src/mobile/mobileLiveSessions.ts");
  const sessions = readLiveSessions({ items: [
    { device_id: "dev_1", device_name: "Mac", fresh: true, sessions: [
      { peer: "uds:/tmp/cc-socks/1.sock", name: "", cwd: "/Users/dev/PRIV", status: "busy", profile: "default", engine: "claude_code",
        last_message: { id: "lm_1", direction: "in", text: "Done", state: "received" } },
      { peer: "http://evil", name: "x" }] },
    { device_name: "no id" }] });
  assert.equal(sessions.length, 1);
  assert.equal(sessions[0].name, "PRIV");
  assert.equal(sessions[0].last.text, "Done");
  // The server names the engine of every session. A Codex session without a name or folder is "Codex".
  assert.equal(sessions[0].engine, "claude_code");
  const codex = readLiveSessions({ items: [{ device_id: "dev_2", sessions: [{ peer: "uds:/tmp/x.sock", engine: "codex" }] }] });
  assert.equal(codex[0].engine, "codex");
  assert.equal(codex[0].name, "Codex");
  assert.deepEqual(readLiveSessions(null), []);
  const thread = readLiveMessages({ running: true, items: [
    { id: "a", direction: "out", text: "hi", state: "delivered" },
    { id: "b", direction: "out", text: "hi", state: "altered", reason: "relay_changed_text" },
    { id: "c", direction: "out", text: "hi", state: "sent" },
    { id: "d", direction: "out", text: "hi", state: "failed", reason: "weird" },
    { direction: "in" }] });
  assert.equal(thread.running, true);
  assert.deepEqual(thread.items.map(liveDeliveryLabel), ["Delivered", "Not delivered as written", "Sending…", "Not delivered"]);
});

test("files a turn made on the Mac: newest first, once per job and path, shown by kind", async () => {
  const { macFiles, macFileKind, fileSize } = await import("../../src/mobile/mobileFilesArtifacts.ts");
  const jobs = [{ id: "dj_1", events: [
    { seq: 3, body: { kind: "files", files: [{ path: "out/report.md", size: 2048 }, { path: "a.png", size: 10 }] } },
    { seq: 9, body: { kind: "files", files: [{ path: "out/report.md", size: 4096 }, { size: 1 }] } },
    { seq: 10, body: { kind: "text", text: "Done" } }] }];
  assert.deepEqual(macFiles(jobs).map((f) => [f.path, f.size, f.name]),
    [["out/report.md", 4096, "report.md"], ["a.png", 10, "a.png"]]);
  assert.equal(macFileKind("chart.PNG"), "image");
  assert.equal(macFileKind("page.html"), "page"); // a page opens sandboxed (artifacts)
  assert.equal(macFileKind("deck.pptx"), "download");
  assert.equal(fileSize(2048), "2 KB");
});

test("the context fill comes from the Mac's latest report, with its window when known", async () => {
  const { contextUsage, contextLabel } = await import("../../src/mobile/mobileUsageModel.ts");
  assert.equal(contextUsage([{ events: [] }]), null);
  const jobs = [{ events: [
    { seq: 1, body: { kind: "context", tokens: 12000 } },
    { seq: 2, body: { kind: "text", text: "x" } },
    { seq: 3, body: { kind: "context", tokens: 48000, window: 1000000 } },
    { seq: 4, body: { kind: "context", tokens: 52000 } }] }];
  const usage = contextUsage(jobs);
  assert.deepEqual(usage, { tokens: 52000, window: 1000000, percent: 5 });
  assert.equal(contextLabel(usage), "Context 52k / 1M · 5%");
  assert.equal(contextLabel({ tokens: 900, window: 0, percent: null }), "Context 900");
});

test("the mode picker offers only what the person's role allows in the Workspace", async () => {
  const { readSessionModes, modeChoices } = await import("../../src/mobile/mobileTurnOptions.ts");
  assert.equal(readSessionModes({}), null);
  assert.deepEqual(modeChoices(null).map((c) => c.id), ["", "acceptEdits", "plan", "bypassPermissions"]);
  assert.deepEqual(modeChoices(readSessionModes({ session_modes: ["plan", "default", "acceptEdits"] })).map((c) => c.id),
    ["", "acceptEdits", "plan"]);
  assert.deepEqual(modeChoices(["plan"]).map((c) => c.label), ["Plan only"]);
});

test("refreshing the Home Screen app: the build script is found and the pull is damped", async () => {
  const { scriptOf, pullDistance, PULL_TRIGGER_PX } = await import("../../src/mobile/pullToRefresh.ts");
  assert.equal(scriptOf('<script type="module" crossorigin src="/static/chat/assets/mobile-AB12.js"></script>'),
    "/static/chat/assets/mobile-AB12.js");
  assert.equal(scriptOf('<script src="/x/mobile-CD34.js" type="module"></script>'), "/x/mobile-CD34.js");
  assert.equal(scriptOf("<html></html>"), "");
  assert.equal(pullDistance(100, 80), 0);
  assert.equal(pullDistance(100, 100 + PULL_TRIGGER_PX * 2), PULL_TRIGGER_PX);
  assert.equal(pullDistance(0, 1000), 110);
});

test("the Mac's router suggestion and compactions are read from the turn's events", async () => {
  const { routeSuggestion, routeLabel } = await import("../../src/mobile/mobileTurnOptions.ts");
  const { compactions } = await import("../../src/mobile/mobileUsageModel.ts");
  const jobs = [{ events: [
    { seq: 1, body: { kind: "route", tier: "hard", confidence: 0.92, suggested_model: "claude-opus-5-5", suggested_effort: "high" } },
    { seq: 2, body: { kind: "compaction", pre_tokens: 201000, post_tokens: 38000 } },
    { seq: 3, body: { kind: "route", tier: "trivial", confidence: 0.95, suggested_model: "claude-haiku-5-5", suggested_effort: "low" } },
    { seq: 4, body: { kind: "compaction", pre_tokens: 199000, post_tokens: 41000 } }] }];
  assert.equal(routeLabel(routeSuggestion(jobs)), "Router: Haiku · low · 95 %");
  assert.deepEqual(compactions(jobs), { count: 2, freed: 321000 });
  assert.equal(routeSuggestion([{ events: [] }]), null);
});

test("cases: each PRJ work item with its newest run, waiting runs first, a case without a run kept", () => {
  const items = {
    items: [
      { id: "w1", source_key: "OCX-1", title: "Done one", source_status: "Done", source_url: "https://jira/OCX-1" },
      { id: "w2", source_key: "OCX-2", title: "Needs you", work_state: "in_progress", reporter: "acc-1", reporter_display: "Alex" },
      { id: "w3", source_key: "OCX-3", title: "", assignee_display: "Ana" },
      { title: "no id, skipped" },
    ],
  };
  const runs = {
    runs: [
      { id: "r2-new", work_item_id: "w2", status: "waiting", waiting_kind: "approval", updated_at: "2026-11-08T10:00:00Z" },
      { id: "r2-old", work_item_id: "w2", status: "failed", updated_at: "2026-11-07T10:00:00Z" },
      { id: "r1", work_item: { id: "w1" }, status: "completed", outcome: "success", updated_at: "2026-11-08T09:00:00Z" },
      { id: "r-x", status: "running" },
    ],
  };
  const cases = readCases(items, runs);
  assert.deepEqual(cases.map((entry) => entry.key), ["OCX-2", "OCX-1", "OCX-3"]);
  assert.equal(cases[0].run?.id, "r2-new");
  assert.equal(cases[0].run?.waitingKind, "approval");
  assert.equal(cases[0].reporter, "Alex");
  assert.equal(cases[0].state, "in_progress");
  assert.equal(cases[1].state, "Done");
  assert.equal(cases[1].url, "https://jira/OCX-1");
  assert.equal(cases[2].run, null);
  assert.equal(cases[2].title, "OCX-3");
  assert.equal(cases[2].assignee, "Ana");
});

test("cases: no Work operator role (403 → null) or junk answers give no cases", () => {
  assert.deepEqual(readCases(null, null), []);
  assert.deepEqual(readCases({ items: "x" }, { runs: [null] }), []);
});

test("artifacts: Claude Code's own artifact links only from the Artifact tool, once each, newest first", () => {
  const jobs = [{ events: [
    { seq: 1, body: { kind: "tool_use", tool: "Artifact", tool_use_id: "u1" } },
    { seq: 2, body: { kind: "tool_result", tool_use_id: "u1", output: "Published: https://claude.ai/code/artifact/0b6f1c2a-aaaa-bbbb" } },
    { seq: 3, body: { kind: "tool_use", tool: "Bash", tool_use_id: "u2" } },
    { seq: 4, body: { kind: "tool_result", tool_use_id: "u2", output: "see https://claude.ai/artifact/evil123456" } },
    { seq: 5, body: { kind: "tool_use", tool: "Artifact", tool_use_id: "u3" } },
    { seq: 6, body: { kind: "tool_result", tool_use_id: "u3", is_error: true, output: "https://claude.ai/artifact/failed12345" } },
    { seq: 7, body: { kind: "tool_use", tool: "Artifact", tool_use_id: "u4" } },
    { seq: 8, body: { kind: "tool_result", tool_use_id: "u4", output: "https://claude.ai/artifact/second1234 and again https://claude.ai/code/artifact/0b6f1c2a-aaaa-bbbb" } },
  ] }];
  assert.deepEqual(claudeArtifacts(jobs).map((item) => item.url), [
    "https://claude.ai/artifact/second1234",
    "https://claude.ai/code/artifact/0b6f1c2a-aaaa-bbbb",
  ]);
});

test("artifacts: a Server chat's tool artifacts by kind, each path once", () => {
  const messages = [
    { id: "m1", toolEvents: [{ artifacts: [
      { name: "report.html", path: "/ws/s1/report.html" },
      { name: "Flow.drawio", path: "diagram://d1" },
    ] }] },
    { id: "m2", toolEvents: [{ artifacts: [
      { name: "plan.docx", path: "/ws/s1/plan.docx" },
      { path: "/ws/s1/data.csv" },
      { name: "report.html", path: "/ws/s1/report.html" },
    ] }, { artifacts: null }] },
    { id: "m3" },
  ];
  assert.deepEqual(serverArtifacts(messages).map((item) => [item.name, item.kind]), [
    ["data.csv", "other"],
    ["plan.docx", "office"],
    ["Flow.drawio", "diagram"],
    ["report.html", "page"],
  ]);
  assert.deepEqual(serverArtifacts(null), []);
});

test("artifacts: HTML and SVG files from the Mac open as pages", () => {
  assert.equal(macFileKind("design.html"), "page");
  assert.equal(macFileKind("logo.SVG"), "page");
  assert.equal(macFileKind("notes.md"), "text");
  assert.equal(macFileKind("shot.png"), "image");
});

test("artifacts: the page policy comes first and allows no network, frames, forms or outside pictures", () => {
  const doc = pageSrcDoc("<html><body><script>fetch('/api')</script></body></html>");
  assert.ok(doc.startsWith('<meta http-equiv="Content-Security-Policy"'));
  for (const rule of ["default-src 'none'", "connect-src 'none'", "frame-src 'none'", "form-action 'none'",
    "img-src data: blob:", "base-uri 'none'"]) assert.ok(PAGE_CSP.includes(rule), rule);
  assert.ok(!PAGE_CSP.includes("'self'"));
  assert.ok(!PAGE_CSP.includes('"'));
});

test("tasks: counts per state in the platform's flow order, unknown states last, the total summed", () => {
  const counts = readTaskCounts({ total: 3, state_counts: { development: 27, intake: 229, blocked: 1, custom_step: 2, review: 0 } });
  assert.deepEqual(counts.states.map((item) => [item.label, item.count]), [
    ["Intake", 229], ["In development", 27], ["Blocked", 1], ["Custom step", 2]]);
  assert.equal(counts.total, 259);
  assert.deepEqual(readTaskCounts({ total: 4 }), { total: 4, states: [] });
  assert.deepEqual(readTaskCounts(null), { total: 0, states: [] });
  assert.equal(stateLabel("ready_for_development"), "Ready");
  assert.equal(stateLabel(""), "Open");
  assert.equal(nextOffset({ next_offset: 50 }), 50);
  assert.equal(nextOffset({ next_offset: null }), null);
});

test("tasks: a page keeps the platform's order; priority and the octryx label come along", () => {
  const page = { items: [
    { id: "a", source_key: "K-1", title: "First", work_state: "intake", priority: "High", labels: ["OCTRYX", "x"] },
    { id: "b", source_key: "K-2", title: "Second", work_state: "review", labels: [] },
  ] };
  const runs = { runs: [{ id: "r", work_item_id: "b", status: "waiting", updated_at: "2026-11-08T10:00:00Z" }] };
  const kept = readCases(page, runs, { keepOrder: true });
  assert.deepEqual(kept.map((item) => item.key), ["K-1", "K-2"]);
  assert.equal(kept[0].automatic, true);
  assert.equal(kept[0].priority, "High");
  assert.equal(kept[1].automatic, false);
  assert.deepEqual(readCases(page, runs).map((item) => item.key), ["K-2", "K-1"]); // Home: waiting first
});

test("task detail: description, type, labels and the three newest comments with text", () => {
  const detail = readTaskDetail({
    id: "w1", description: "  Steps:\n1. open\n2. fail  ", issue_type: "Bug", labels: ["octryx", "backend"],
    comments: [
      { id: "c1", author_display: "Ana", created: "2026-11-01T10:00:00Z", body: "first" },
      { id: "c2", author: "bob", body: "" },
      { id: "c3", author_display: "Alex", body: "second" },
      { id: "c4", author_display: "Ana", body: "third" },
      { id: "c5", author_display: "Ana", body: "fourth" },
    ],
    comments_total: 12,
  });
  assert.equal(detail.description, "Steps:\n1. open\n2. fail");
  assert.equal(detail.issueType, "Bug");
  assert.deepEqual(detail.labels, ["octryx", "backend"]);
  assert.deepEqual(detail.comments.map((comment) => comment.body), ["fourth", "third", "second"]);
  assert.equal(detail.commentsTotal, 12);
  assert.equal(readTaskDetail(null), null);
  assert.equal(readTaskDetail({ title: "no id" }), null);
});

test("task plan: the newest plan that is not superseded, with its open questions", () => {
  const plan = readTaskPlan({ items: [
    { status: "superseded", version: 3 },
    { status: "needs_clarification", version: 2, title: "Fix timeout", understood_request: "Raise the timeout",
      open_questions: ["Which environment?", "", "Keep the retry?"], acceptance_criteria: ["a", "b"] },
    { status: "approved", version: 1 },
  ] });
  assert.equal(plan.status, "needs_clarification");
  assert.equal(plan.version, 2);
  assert.deepEqual(plan.openQuestions, ["Which environment?", "Keep the retry?"]);
  assert.equal(plan.acceptance, 2);
  assert.equal(planStatusLabel(plan.status), "Needs clarification");
  assert.equal(planStatusLabel("ready_for_review"), "Waiting for approval");
  assert.equal(readTaskPlan({ items: [{ status: "superseded" }] }), null);
  assert.equal(readTaskPlan(null), null);
  assert.equal(sourceLabel("servicenow"), "ServiceNow");
  assert.equal(sourceLabel(""), "");
});

test("run responsible: read from the run, said in words; take-over refusals in words", () => {
  const responsible = readResponsible({ user_id: "u1", display_name: "Jane Doe", source: "taken_over" });
  assert.equal(responsibleText(responsible), "Jane Doe (took it over)");
  assert.equal(responsibleText(readResponsible({ user_id: "u2", source: "reporter" })), "Someone (reporter)");
  assert.equal(readResponsible(null), null);
  assert.equal(readResponsible({ display_name: "no id" }), null);
  const cases = readCases({ items: [{ id: "w", source_key: "K" }] },
    { runs: [{ id: "r", work_item_id: "w", status: "waiting", responsible: { user_id: "u3", display_name: "Ana", source: "assignee" } }] });
  assert.equal(cases[0].run.responsible.name, "Ana");
  assert.equal(runRefusalText("already_responsible"), "You are already responsible for this run.");
  assert.equal(runRefusalText("some_new_code"), "some new code");
  assert.match(runRefusalText("workspace_required"), /needs one: move the task to a Workspace/);
  assert.match(runRefusalText("server_build_not_allowed"), /not allowed on the Octryx server\. Run it on your Mac/);
  assert.equal(runRefusalText(null), "The action was refused.");
});

test("start a run: the startable workflows, and the one proposed from the task's kind and state", () => {
  const flows = readStartable({ workflows: [
    { key: "jira-intake-triage", title: "Jira intake & triage", kind: "phased" },
    { key: "epic-delivery", title: "Story / epic delivery", kind: "phased" },
    { key: "bug-fix-reproduction", title: "Bug fix", kind: "phased" },
    { key: "incident-analysis", title: "Incident / alert analysis", kind: "phased" },
    { title: "no key" },
  ] });
  assert.equal(flows.length, 4);
  assert.equal(suggestWorkflow(flows, "intake", "Task"), "jira-intake-triage");
  assert.equal(suggestWorkflow(flows, "ready_for_development", "Story"), "epic-delivery");
  assert.equal(suggestWorkflow(flows, "intake", "Bug"), "bug-fix-reproduction");
  assert.equal(suggestWorkflow(flows, "development", "Incident"), "incident-analysis");
  // Only what the Workspace offers is proposed; the triage, else the first, is the fallback.
  const few = readStartable({ workflows: [{ key: "pr-fix", title: "PR fix" }, { key: "jira-intake-triage" }] });
  assert.equal(suggestWorkflow(few, "development", "Bug"), "jira-intake-triage");
  assert.equal(suggestWorkflow(readStartable({ workflows: [{ key: "pr-fix" }] }), "intake", "Task"), "pr-fix");
  assert.equal(suggestWorkflow([], "intake", "Task"), "");
  assert.deepEqual(readStartable(null), []);
});

test("live pictures: scaled down to fit, never up; the count comes with the message; a broken one says so", () => {
  assert.deepEqual(fitInside(3024, 4032, 1600), { width: 1200, height: 1600 });
  assert.deepEqual(fitInside(1179, 2556, 1600), { width: 738, height: 1600 });
  assert.deepEqual(fitInside(800, 600, 1600), { width: 800, height: 600 });
  assert.equal(MAX_PICTURES, 3);
  const message = readLiveMessage({ id: "lm_1", direction: "out", text: "(picture)", state: "failed",
    reason: "attachment_missing", attachments: 2 });
  assert.equal(message.attachments, 2);
  assert.equal(liveDeliveryLabel(message), "The picture did not arrive whole");
  assert.equal(readLiveMessage({ id: "lm_2", text: "hi" }).attachments, 0);
});

test("live progress: steps read, merged by seq, a tool and its result as one step", () => {
  const page = readLiveProgress({ status: "busy", running: true, last_seq: 5, events: [
    { seq: 1, kind: "prompt", from: "octryx", text: "Status?", at: "2026-11-09T08:00:00Z" },
    { seq: 2, kind: "text", text: "Running the tests.", at: "2026-11-09T08:00:01Z" },
    { seq: 3, kind: "tool", id: "t1", tool: "Bash", input: "npm test", at: "2026-11-09T08:00:02Z" },
    { seq: 4, kind: "tool", id: "t2", tool: "Read", input: "src/a.ts", at: "2026-11-09T08:00:03Z" },
    { seq: 5, kind: "result", id: "t1", ok: false, line: "2 failing", at: "2026-11-09T08:00:09Z" },
    { seq: 6, kind: "thinking", text: "never shown" },
  ] });
  assert.equal(page.events.length, 5);
  assert.equal(liveStatusText(page.status, page.running), "Working…");
  assert.equal(liveStatusText("idle", true), "Idle");
  assert.equal(liveStatusText("busy", false), "Not reporting");
  const steps = progressSteps(page.events);
  assert.deepEqual(steps.map((step) => step.kind), ["prompt", "text", "tool", "tool"]);
  assert.deepEqual([steps[2].done, steps[2].ok, steps[2].line], [true, false, "2 failing"]);
  assert.equal(steps[3].done, false); // the Read call has no result yet: still running
  const merged = mergeProgress(page.events, readLiveProgress({ events: [
    { seq: 5, kind: "result", id: "t1", ok: false, line: "2 failing" },
    { seq: 7, kind: "result", id: "t2", ok: true },
  ] }).events, 4);
  assert.deepEqual(merged.map((event) => event.seq), [3, 4, 5, 7]);
  assert.equal(progressSteps(merged).filter((step) => step.kind === "tool" && step.done).length, 2);
});

test("live progress groups: tools between narration collapse into one line, failures and the running step stand out", () => {
  const tool = (seq, name, input) => ({ seq, kind: "tool", id: `t${seq}`, tool: name, input, at: "" });
  const result = (seq, ok = true) => ({ seq: seq + 100, kind: "result", id: `t${seq}`, ok, line: ok ? "" : "boom", at: "" });
  const events = [
    { seq: 1, kind: "text", text: "Looking around.", at: "" },
    tool(2, "Bash", "cd /repo && grep -rn executionTarget app/web"), result(2),
    tool(3, "Bash", "git status"), result(3),
    tool(4, "Read", "/repo/app/web/_helpers/serialization.py"), result(4),
    tool(5, "Bash", "npm test"), result(5),
    tool(6, "Bash", "ls"), result(6),
    { seq: 7, kind: "text", text: "Now fixing.", at: "" },
    tool(8, "Edit", "/repo/app/x.py"), result(8, false),
    tool(9, "Bash", "pytest -q"),
  ];
  const steps = progressSteps(events); // each call, then its result, as they arrive
  const blocks = groupSteps(steps);
  assert.deepEqual(blocks.map((block) => block.kind), ["step", "tools", "step", "tools"]);
  assert.equal(groupSummary(blocks[1]), "5 steps · Bash ×4 · Read");
  assert.equal(blocks[1].running, false);
  assert.equal(groupSummary(blocks[3]), "1 of 2 failed");
  assert.equal(blocks[3].running, true);
  assert.equal(blocks[1].key, "g-p-2"); // stable across reloads: the first call's seq
  assert.equal(shortStep(blocks[1].tools[0]), "grep -rn executionTarget app/web");
  assert.equal(shortStep(blocks[1].tools[2]), "serialization.py");
  assert.equal(shortStep({ tool: "Bash", input: "x".repeat(100) }).length, 60);
  assert.equal(shortStep({ tool: "Bash", input: "cd /repo && JWT_SECRET=x FORCE=1 python -m pytest -q" }),
    "pytest -q");
});

test("forks: a thread that continues a copy is written to through the take-over with its own thread", () => {
  const sessions = readLocalSessions({ items: [
    { id: "ls1", profile: "team", title: "octryx-pet", folder: "/x", folder_name: "x", thread_id: "th-own",
      fork_thread_ids: ["th-fork-1", "th-fork-2"], takeover_allowed: true, device: { name: "Mac", online: true } },
  ] });
  assert.deepEqual(sessions[0].forkThreadIds, ["th-fork-1", "th-fork-2"]);
  assert.deepEqual(takeOverTarget(sessions, "th-own"), { localSessionId: "ls1" });
  assert.deepEqual(takeOverTarget(sessions, "th-fork-2"), { localSessionId: "ls1", forkThreadId: "th-fork-2" });
  assert.equal(takeOverTarget(sessions, "th-other"), null);
  assert.equal(isFork("Fork of octryx-pet"), true);
  assert.equal(isFork("Pricing refactor"), false);
});

test("A Mac chat asks only for new events and keeps the ones it has", () => {
  const ev = (seq) => ({ seq, type: "job_event", body: {} });
  const before = [
    { id: "dj_a", status: "finished", events: [ev(1), ev(2), ev(3)] },
    { id: "dj_b", status: "running", events: [ev(1), ev(2)] },
    { id: "dj_c", status: "offered", events: [] },
  ];
  assert.equal(knownSeqs(before), "dj_a:3,dj_b:2");
  const raw = { items: [
    { id: "dj_a", partial: true, since: 3, events: [] },
    { id: "dj_b", partial: true, since: 2, events: [ev(2), ev(3), ev(4)] },
    { id: "dj_c", events: [ev(1)] },
    { id: "dj_d", events: [ev(1)] },
  ] };
  const partial = partialJobIds(raw);
  assert.deepEqual([...partial].sort(), ["dj_a", "dj_b"]);
  const fresh = [
    { id: "dj_a", status: "finished", events: [] },
    { id: "dj_b", status: "waiting", events: [ev(2), ev(3), ev(4)] },
    { id: "dj_c", status: "running", events: [ev(1)] },
    { id: "dj_d", status: "offered", events: [ev(1)] },
  ];
  const merged = mergeJobs(before, fresh, partial);
  assert.deepEqual(merged.map((job) => [job.id, job.status, job.events.map((e) => e.seq)]), [
    ["dj_a", "finished", [1, 2, 3]],
    ["dj_b", "waiting", [1, 2, 3, 4]],
    ["dj_c", "running", [1]],
    ["dj_d", "offered", [1]],
  ]);
  assert.deepEqual(mergeJobs(before, [], new Set()), []); // a job no longer listed is dropped
});

test("one-line steps name files, not paths", () => {
  const bash = (input) => shortStep({ tool: "Bash", input });
  assert.equal(bash("/Volumes/data/project/venv/bin/python -m pytest -q tests/test_live.py"),
    "pytest -q tests/test_live.py");
  assert.equal(bash("sed -n 117,124p /Volumes/data/project/docs/PLAN.md"),
    "reads PLAN.md lines 117–124");
  assert.equal(bash("cd /Volumes/x && head -40 /Volumes/x/backend/app/services/devices/live.py"), "reads live.py");
  assert.equal(bash("cat ~/.zshrc"), "reads .zshrc");
  assert.equal(bash("grep -rn executionTarget /Volumes/data/project/backend/app/web"),
    "grep -rn executionTarget web");
  assert.equal(bash("git -C /Volumes/data/project status --short"), "git -C project status --short");
  assert.equal(bash("/usr/bin/env python3 -c 'print(1)'"), "env python3 -c 'print(1)'");
  assert.equal(bash("npm test"), "npm test");
  assert.equal(shortStep({ tool: "Grep", input: "executionTarget in /Volumes/a/b/app/web" }), "executionTarget in web");
});

