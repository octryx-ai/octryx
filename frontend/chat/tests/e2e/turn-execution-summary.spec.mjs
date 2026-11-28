import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, ensureSignedIn } from "./helpers.mjs";
import {
  PROFILE_DECISION_SOURCES,
  buildSummaryFixture,
  profileSection,
} from "./turnExecutionSummaryFixtures.mjs";

// Turn Execution Summary v1. Bootstrap is patched with synthetic
// assistant turns so the scenario does not depend on a live provider; the
// summary endpoint is mocked per trace id with backend-exact fixtures and the
// session websocket is mocked so approval/run-state events are deterministic.

const FALLBACK_SESSION_ID = "e2e-turn-summary-session";

// The only non-GET request tolerated anywhere in this test: the login form
// submit during sign-in setup, before the no-write observation window.
const SETUP_WRITE_ALLOW_LIST = [{ method: "POST", pathname: "/chat/login" }];

// The timeline is virtualized; a tall viewport keeps every synthetic turn
// mounted so each card is observable without scrolling (and remounting).
test.use({ viewport: { width: 1280, height: 2400 } });

// The run_state event triggers a silent bootstrap reload; drop in-flight
// route handlers so teardown cannot race a pending route.fetch.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

function assistantMessage(id, traceId, content, toolEvents = []) {
  return {
    id,
    role: "assistant",
    content,
    model: "e2e-model",
    runtimeLabel: "E2E runtime",
    createdAt: "2026-09-27T10:00:00Z",
    toolEvents,
    turnTraceId: traceId,
    feedback: null,
  };
}

// Real approval pauses end on a tool-only assistant message: empty content
// and the tool event that is waiting for the approval decision.
const WAITING_TOOL_EVENT = {
  id: "tool-event-deploy",
  messageId: "msg-waiting",
  toolName: "deploy_release",
  parameters: { release: "e2e" },
  result: { status: "pending_approval" },
  status: "pending_approval",
  durationMs: null,
  createdAt: "2026-09-27T10:00:00Z",
};

const ALLOWED_PROFILE = profileSection({
  profileId: "direct_chat_safe",
  status: "allowed",
  decisionSource: PROFILE_DECISION_SOURCES.directChat,
  executionStrategy: "direct",
});

function blockedProfile(status) {
  return profileSection({
    profileId: "workflow:e2e-release",
    status,
    decisionSource: null,
    workflowKey: "e2e-release",
  });
}

const AGENT = { id: "agent-e2e", name: "E2E Agent" };
const MODEL = { provider: "e2e", model: "e2e-model" };

function approval(status) {
  return {
    approval_id: "approval-e2e",
    tool_name: "deploy_release",
    status,
    created_at: "2026-09-27T10:00:00Z",
    resolved_at: status === "pending" ? null : "2026-09-27T10:01:00Z",
  };
}

const TURNS = [
  { id: "msg-finished", trace: "trace-finished", text: "Finished turn body." },
  { id: "msg-config", trace: "trace-config", text: "Configuration blocked body." },
  { id: "msg-no-snapshot", trace: "trace-no-snapshot", text: "Unrecorded turn body." },
  { id: "msg-flaky", trace: "trace-flaky", text: "Flaky summary body." },
  { id: "msg-intermediate", trace: "trace-intermediate", text: "Intermediate step body." },
  { id: "msg-waiting", trace: "trace-waiting", text: "", toolEvents: [WAITING_TOOL_EVENT] },
  { id: "msg-missing", trace: "trace-missing", text: "Missing summary body." },
];

function summaryFor(traceId, sessionId, { flakyRecovered, approvalResolved }) {
  const base = { traceId, sessionId };
  switch (traceId) {
    case "trace-finished":
      return buildSummaryFixture({
        ...base,
        reasonCode: "runtime_finished",
        profile: ALLOWED_PROFILE,
        agent: AGENT,
        model: MODEL,
        capabilities: [{ name: "web_search", calls: 2, succeeded: 2, failed: 0 }],
        artifacts: [{ artifact_id: "artifact-1", tool_name: "write_report", size_bytes: 2048, created_at: null }],
        usage: { tokens_in: 12, tokens_out: 34 },
      });
    case "trace-config":
      return buildSummaryFixture({
        ...base,
        reasonCode: "gate_needs_configuration",
        profile: blockedProfile("needs_configuration"),
        agent: AGENT,
      });
    case "trace-no-snapshot":
      return buildSummaryFixture({ ...base, reasonCode: "missing_snapshot" });
    case "trace-flaky":
      return !flakyRecovered
        ? null
        : buildSummaryFixture({ ...base, reasonCode: "gate_denied", profile: blockedProfile("denied"), agent: AGENT });
    case "trace-intermediate":
      return buildSummaryFixture({
        ...base,
        reasonCode: "intermediate_trace",
        profile: ALLOWED_PROFILE,
        agent: AGENT,
        model: MODEL,
      });
    case "trace-waiting":
      // The paused trace never records a finished marker; once the approval is
      // resolved the backend reports `runtime_outcome_unknown`, not finished.
      return buildSummaryFixture({
        ...base,
        reasonCode: approvalResolved ? "runtime_outcome_unknown" : "approval_pending",
        profile: ALLOWED_PROFILE,
        agent: AGENT,
        model: MODEL,
        capabilities: [{ name: "deploy_release", calls: 1, succeeded: approvalResolved ? 1 : 0, failed: 0 }],
        approvals: [approval(approvalResolved ? "approved" : "pending")],
      });
    default:
      return undefined;
  }
}

function observeRequests(page) {
  const observation = { phase: "setup", violations: [], summaryMethods: [] };
  page.on("request", (request) => {
    const method = request.method();
    const { pathname } = new URL(request.url());
    if (pathname.endsWith("/execution-summary")) {
      observation.summaryMethods.push(method);
    }
    if (method === "GET") {
      return;
    }
    const allowed =
      observation.phase === "setup" &&
      SETUP_WRITE_ALLOW_LIST.some((entry) => entry.method === method && entry.pathname === pathname);
    if (!allowed) {
      observation.violations.push(`${observation.phase}: ${method} ${pathname}`);
    }
  });
  return observation;
}

async function installMocks(page) {
  // The flaky trace fails until the test explicitly recovers it, so any
  // number of initial mounts still observes the error state.
  const state = {
    sessionId: FALLBACK_SESSION_ID,
    approvalResolved: false,
    flakyRecovered: false,
    sessionSocket: null,
  };
  const summaryRequests = [];

  await page.routeWebSocket(/\/api\/v1\/sessions\/[^/]+\/ws/, (socket) => {
    state.sessionSocket = socket;
  });
  await page.routeWebSocket(/\/api\/v1\/canvas\/sessions\/[^/]+\/ws/, () => {});

  await page.route("**/chat/api/bootstrap**", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const selectedSession = {
      ...(payload.selectedSession ?? {
        id: FALLBACK_SESSION_ID,
        title: "Turn summary e2e",
        status: "active",
        projectName: payload.selectedProject?.name ?? "",
        runtimeTargetId: payload.selectedRuntimeTargetId ?? "",
        runtimeLabel: payload.selectedRuntimeLabel ?? "",
        startedAt: "2026-09-27T10:00:00Z",
      }),
      streamToken: "e2e-stream-token",
    };
    state.sessionId = selectedSession.id;
    await route.fulfill({
      response,
      json: {
        ...payload,
        selectedSession,
        selectedSessionIsArchived: false,
        selectedSessionIsRunning: false,
        selectedMessagesHasMore: false,
        selectedMessages: [
          {
            id: "msg-user",
            role: "user",
            content: "Run the e2e turn.",
            createdAt: "2026-09-27T09:59:00Z",
            toolEvents: [],
          },
          ...TURNS.map((turn) => assistantMessage(turn.id, turn.trace, turn.text, turn.toolEvents)),
        ],
      },
    });
  });

  await page.route("**/chat/api/turn-traces/*/execution-summary", async (route) => {
    const traceId = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2));
    summaryRequests.push(traceId);
    const json = summaryFor(traceId, state.sessionId, {
      flakyRecovered: state.flakyRecovered,
      approvalResolved: state.approvalResolved,
    });
    if (json === null) {
      return route.fulfill({ status: 500, json: { detail: "internal secret detail" } });
    }
    if (json === undefined) {
      return route.fulfill({ status: 404, json: { detail: "Not found" } });
    }
    return route.fulfill({ json });
  });

  await page.route("**/chat/api/turn-traces/*", async (route) => {
    if (route.request().url().endsWith("/execution-summary")) {
      return route.fallback();
    }
    const traceId = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1));
    return route.fulfill({
      json: {
        id: traceId,
        provider: "e2e",
        model: "e2e-model",
        inputMessages: [],
        contextSnapshot: {},
        toolTrace: [],
        rawOutput: {},
        usage: {},
        createdAt: "2026-09-27T10:00:00Z",
        // The turn's model calls (seat/API gateway): the trace lists them, one line each.
        calls: [
          { id: `${traceId}-call-1`, provider: "e2e", model: "e2e-model", createdAt: "2026-09-27T09:59:58Z",
            tokens: { input: 1200, output: 7, cacheRead: 0, cacheCreation: 0 }, durationMs: 1500, stopReason: "tool_use" },
          { id: traceId, provider: "e2e", model: "e2e-model", createdAt: "2026-09-27T10:00:00Z",
            tokens: { input: 300, output: 40, cacheRead: 0, cacheCreation: 0 }, durationMs: 900, stopReason: "end_turn" },
        ],
        promptOnDevice: false,
      },
    });
  });

  const countFor = (traceId) => summaryRequests.filter((entry) => entry === traceId).length;
  return { state, countFor };
}

function rowFor(page, text) {
  return page.locator("article.message-row--assistant").filter({ hasText: text });
}

function cardIn(row) {
  return row.getByRole("region", { name: "Turn execution status" });
}

function cardFor(page, text) {
  return cardIn(rowFor(page, text));
}

test("turn execution summary cards render server state without mutations", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const observation = observeRequests(page);
  const { state, countFor } = await installMocks(page);
  await ensureSignedIn(page);
  // No-write observation window: from here on every request must be a GET.
  observation.phase = "observe";

  const finished = cardFor(page, "Finished turn body.");
  await expect(finished).toContainText("Finished, unverified");
  await expect(finished).toHaveAttribute("data-state-tone", "neutral");

  const config = cardFor(page, "Configuration blocked body.");
  await expect(config).toContainText("Needs configuration");
  await expect(config).toContainText("This request requires configuration before it can run.");
  await expect(config).toContainText("Complete the missing configuration, then retry.");
  await expect(config).toHaveAttribute("data-state-tone", "attention");

  const noSnapshot = cardFor(page, "Unrecorded turn body.");
  await expect(noSnapshot).toContainText("Status unknown");
  await expect(noSnapshot).toContainText("No execution decision was recorded for this turn.");

  await expect(cardFor(page, "Missing summary body.")).toContainText("Unavailable");

  // An intermediate step of a longer turn shows no card; the final (tool-only)
  // message of that turn carries the outcome.
  await expect(rowFor(page, "Intermediate step body.")).toBeVisible();
  await expect.poll(() => countFor("trace-intermediate")).toBeGreaterThan(0);
  await expect(cardFor(page, "Intermediate step body.")).toHaveCount(0);

  const flaky = cardFor(page, "Flaky summary body.");
  await expect(flaky).toContainText("Status not available.");
  await expect(flaky).not.toContainText("secret");
  await expect(page.getByText("Flaky summary body.")).toBeVisible();
  state.flakyRecovered = true;
  await flaky.getByRole("button", { name: "Try again" }).click();
  await expect(flaky).toContainText("Denied");
  await expect(flaky).toContainText("Ask an administrator to review the execution policy.");
  await expect(flaky).toHaveAttribute("data-state-tone", "blocked");

  // Approval resolved elsewhere: the session stream reports the run-state
  // change and the mounted waiting card refetches its GET without remounting.
  const waitingRow = page.locator("article.message-row--tool-only");
  await expect(waitingRow).toHaveCount(1);
  const waiting = cardIn(waitingRow);
  await expect(waiting).toContainText("Waiting for approval");
  await expect(waiting).toContainText("Approve or reject the pending action.");
  await expect(waiting).toHaveAttribute("data-state-tone", "attention");
  await waitingRow.evaluate((node) => {
    node.dataset.e2eMount = "original";
  });
  await waiting.evaluate((node) => {
    node.dataset.e2eMount = "original";
  });
  expect(state.sessionSocket).not.toBeNull();
  const before = Object.fromEntries(TURNS.map((turn) => [turn.trace, countFor(turn.trace)]));

  state.approvalResolved = true;
  state.sessionSocket.send(JSON.stringify({ type: "run_state", status: "idle" }));

  await expect(waiting).toContainText("Status unknown");
  await expect(waiting).toContainText("The runtime outcome of this turn is not recorded.");
  await expect(waiting).not.toContainText("Finished");
  await expect(waiting).not.toContainText("Approve or reject the pending action.");
  await expect(waiting).toHaveAttribute("data-state-tone", "neutral");
  await expect(waiting).toHaveAttribute("data-e2e-mount", "original");
  await expect(waitingRow).toHaveAttribute("data-e2e-mount", "original");
  expect(countFor("trace-waiting")).toBe(before["trace-waiting"] + 1);
  // Bounded: settled, snapshot-less and unavailable summaries are never refetched.
  // Proving an absence needs a quiet window longer than the refresh coalescing.
  await page.waitForTimeout(750);
  for (const traceId of [
    "trace-finished",
    "trace-config",
    "trace-no-snapshot",
    "trace-flaky",
    "trace-missing",
    "trace-intermediate",
  ]) {
    expect(countFor(traceId), traceId).toBe(before[traceId]);
  }

  await finished.getByRole("button", { name: "Open execution details" }).click();
  const details = page.getByRole("dialog", { name: "Execution trace" }).getByRole("region", {
    name: "Execution summary",
  });
  await expect(details).toContainText("direct_chat_safe");
  await expect(details).toContainText("execution_profile");
  await expect(details).toContainText("web_search");
  await expect(details).toContainText("write_report");
  await expect(details).toContainText("2 calls · 2 succeeded");

  await expect(page.getByRole("textbox", { name: /Message Octryx/i })).toBeEnabled();
  expect(observation.summaryMethods.length).toBeGreaterThan(0);
  expect(new Set(observation.summaryMethods)).toEqual(new Set(["GET"]));
  expect(observation.violations).toEqual([]);
  expect(runtimeErrors.filter((entry) => !/404|500/.test(entry))).toEqual([]);
});

// An answer's "Open trace" (its actions menu) shows what was sent: the execution trace with the turn's model calls.
test("an answer's trace opens from its actions menu and lists the turn's model calls", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const { state } = await installMocks(page);
  state.flakyRecovered = true; // the other test's deliberate 500 is not part of this one
  await ensureSignedIn(page);

  const row = rowFor(page, "Finished turn body.");
  await expect(row).toBeVisible();
  await row.hover();
  await row.getByRole("button", { name: "More actions for this answer" }).click();
  await page.getByText("Open trace", { exact: true }).click();

  const calls = page.getByTestId("trace-calls");
  await expect(calls).toContainText("2 model calls");
  await expect(calls.getByTestId("trace-call")).toHaveCount(2);
  // The shared fixtures answer one summary with 404 on purpose (a turn without one); no page error may occur.
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});
