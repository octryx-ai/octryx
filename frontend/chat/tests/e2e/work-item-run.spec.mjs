import { expect, test } from "@playwright/test";

import { collectRuntimeErrors, openWorkspaceArea } from "./helpers.mjs";
import { buildSummaryFixture } from "./turnExecutionSummaryFixtures.mjs";

// Work › Work items → an item → its workflow runs → the run's chat with the turn's execution summary. A fresh e2e
// database has no synced items, so the item, its run and the run's thread are mocked in the servers' shapes.

const ITEM = {
  id: "wi-e2e-1",
  project_id: "ws-e2e-1",
  source_type: "jira",
  source_instance: "jira.example.test",
  source_key: "SHOP-42",
  source_project_key: "SHOP",
  title: "Checkout shows the wrong total",
  issue_type: "Bug",
  source_status: "In Progress",
  work_state: "in_progress",
  labels: [],
  components: [],
  watchers: [],
  comments: [],
};
const RUN = {
  id: "run-e2e-1",
  title: "Bug fix with a reproduction test",
  workflow_key: "bug-fix-reproduction",
  workflow_kind: "delivery",
  status: "finished",
  waiting_kind: null,
  pause_reason: null,
  outcome: "success",
  session_id: "sess-run-e2e-1",
  updated_at: "2026-11-21T10:00:00Z",
};
const TRACE_ID = "trace-run-e2e-1";
const ANSWER = "The reproduction test fails before the fix and passes after it.";

async function installMocks(page) {
  await page.route(/\/api\/v1\/secure-work\/work-items\?/, (route) =>
    route.fulfill({ json: { items: [ITEM], total: 1, limit: 200, offset: 0, next_offset: null } }));
  await page.route(`**/api/v1/secure-work/work-items/${ITEM.id}`, (route) => route.fulfill({ json: ITEM }));
  await page.route(/\/api\/v1\/workflow-runs\?work_item_id=/, (route) => route.fulfill({ json: { runs: [RUN] } }));

  // The run's thread: one prompt and the agent's answer with its trace.
  await page.routeWebSocket(/\/api\/v1\/sessions\/[^/]+\/ws/, () => {});
  await page.routeWebSocket(/\/api\/v1\/canvas\/sessions\/[^/]+\/ws/, () => {});
  await page.route("**/chat/api/bootstrap**", async (route) => {
    if (!route.request().url().includes(RUN.session_id)) return route.fallback();
    const response = await route.fetch();
    const payload = await response.json();
    await route.fulfill({
      response,
      json: {
        ...payload,
        selectedSession: { id: RUN.session_id, title: `${ITEM.source_key} ${ITEM.title}`, status: "active",
          projectName: payload.selectedProject?.name ?? "", startedAt: "2026-11-21T09:58:00Z",
          streamToken: "e2e-stream-token" },
        selectedSessionIsArchived: false,
        selectedSessionIsRunning: false,
        selectedMessagesHasMore: false,
        selectedMessages: [
          { id: "msg-run-user", role: "user", content: `Fix ${ITEM.source_key}.`, createdAt: "2026-11-21T09:58:00Z",
            toolEvents: [] },
          { id: "msg-run-answer", role: "assistant", content: ANSWER, model: "e2e-model", runtimeLabel: "E2E runtime",
            createdAt: "2026-11-21T10:00:00Z", toolEvents: [], turnTraceId: TRACE_ID, feedback: null },
        ],
      },
    });
  });
  await page.route(`**/chat/api/turn-traces/${TRACE_ID}/execution-summary`, (route) =>
    route.fulfill({ json: buildSummaryFixture({ traceId: TRACE_ID, sessionId: RUN.session_id, reasonCode: "runtime_finished" }) }));
}

test("a work item opens its workflow runs and a run opens its turn execution summary", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await installMocks(page);

  await openWorkspaceArea(page, "Work");
  await page.getByRole("button", { name: "Work items", exact: true }).click();
  await page.getByRole("tab", { name: "All items", exact: true }).click();
  await page.getByText(ITEM.title).first().click();

  const runs = page.getByTestId("work-detail-runs");
  await expect(runs).toContainText(RUN.title);
  await runs.getByRole("link", { name: "Open the chat" }).click();

  const answer = page.locator("article.message-row--assistant").filter({ hasText: ANSWER });
  await expect(answer).toBeVisible();
  const card = answer.getByRole("region", { name: "Turn execution status" });
  await expect(card).toContainText("Finished, unverified");
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});

// "Start workflow" opens its form where the person looks: in view, the workflow field focused once the list arrived
// (the form opened below the fold and looked like a silent start).
test("Start workflow brings its form into view and focuses the workflow field", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await installMocks(page);
  await page.route(/\/api\/v1\/workflow-runs\/startable/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600)); // the list arrives after the form opened
    await route.fulfill({ json: { workflows: [{ key: RUN.workflow_key, title: RUN.title, kind: "delivery" }],
      entry_workflow: null } });
  });
  await page.route(/\/api\/v1\/workflow-runs\/runtime-targets/, (route) =>
    route.fulfill({ json: { options: [], default: "server" } }));
  await page.setViewportSize({ width: 1280, height: 640 });

  await openWorkspaceArea(page, "Work");
  await page.getByRole("button", { name: "Work items", exact: true }).click();
  await page.getByRole("tab", { name: "All items", exact: true }).click();
  await page.getByText(ITEM.title).first().click();
  await page.getByRole("button", { name: "Start workflow" }).first().click();

  const form = page.getByTestId("work-item-start-section");
  await expect(form).toBeInViewport();
  const workflow = form.getByLabel("Workflow", { exact: true });
  await expect(workflow).toBeFocused();
  await expect(workflow).toBeInViewport();
  expect(runtimeErrors.filter((entry) => entry.startsWith("pageerror"))).toEqual([]);
});

// A workflow that builds on the server is refused; the refusal leads to the launcher install page (outsider
// walkthrough: it named "Agents › Install octryx-claude" without a link).
test("a refused server build leads to the launcher install page", async ({ page }) => {
  await installMocks(page);
  await page.route(/\/api\/v1\/workflow-runs\/startable/, (route) =>
    route.fulfill({ json: { workflows: [{ key: RUN.workflow_key, title: RUN.title, kind: "phased" }], entry_workflow: null } }));
  await page.route(/\/api\/v1\/workflow-runs\/runtime-targets/, (route) =>
    route.fulfill({ json: { options: [], default: "server" } }));
  await page.route(/\/api\/v1\/workflow-runs$/, (route) => route.request().method() === "POST"
    ? route.fulfill({ status: 409, json: { detail: { code: "server_build_not_allowed",
      message: "This workflow builds or tests the repository, which is not allowed on the Octryx server." } } })
    : route.fallback());

  await openWorkspaceArea(page, "Work");
  await page.getByRole("button", { name: "Work items", exact: true }).click();
  await page.getByRole("tab", { name: "All items", exact: true }).click();
  await page.getByText(ITEM.title).first().click();
  await page.getByRole("button", { name: "Start workflow" }).first().click();
  const form = page.getByTestId("work-item-start-section");
  await form.getByLabel("Workflow", { exact: true }).selectOption(RUN.workflow_key);
  await form.getByRole("button", { name: "Start run" }).click();

  await expect(form.getByRole("alert")).toContainText("not allowed on the Octryx server");
  await expect(form.getByRole("link", { name: "Install octryx-claude" }))
    .toHaveAttribute("href", "/chat?area=agents&agents_view=install");
});
