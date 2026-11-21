// Agents & workflows → Agents (A3): the list rows of Workspace agents and built-ins, filtering, and which agent opens.
import assert from "node:assert/strict";
import { test } from "node:test";
import { selectedListAgent } from "../../src/admin/components/agentsTab/agentListModel.ts";
import { agentRows, filterAgentRows, readAgentsOverview } from "../../src/admin/components/agentsTab/agentsOverviewModel.ts";

const OVERVIEW = readAgentsOverview({
  usage_window_days: 30,
  usage: { "ws-agent": 4 },
  builtins: [
    { key: "default", name: "Default assistant", description: "No agent", capability_ceiling: "read_only", default_workflow_key: "", row: false },
    { key: "coding", name: "Coding agent", description: "Coding", capability_ceiling: "deliver", default_workflow_key: "coding-change-tdd", row: true },
    { key: "subtask", name: "Sub-task worker", description: "Children", capability_ceiling: "change", default_workflow_key: "", row: false },
  ],
});
const AGENTS = [
  { id: "ws-agent", name: "Claims helper", goal: "Explains\n claims", projectId: "ws", capabilityCeiling: "read_only", isActive: true },
  { id: "draft", name: "Draft one", description: "Not yet", projectId: "", capabilityCeiling: "change", isActive: false },
  { id: "coding-row", name: "Coding agent", builtinKey: "coding", capabilityCeiling: "deliver", defaultWorkflowKey: "coding-change-tdd", isActive: true },
];

test("built-ins come first, then Workspace agents, each with ceiling, workflow, scope, use and status", () => {
  const rows = agentRows(AGENTS, OVERVIEW, [{ id: "ws", name: "Claims" }]);
  assert.deepEqual(rows.map((row) => row.name), ["Default assistant", "Coding agent", "Sub-task worker", "Claims helper", "Draft one"]);
  const coding = rows[1];
  assert.deepEqual([coding.id, coding.scope, coding.status[0], coding.defaultWorkflow], ["coding-row", "Built-in", "Built-in", "coding-change-tdd"]);
  assert.equal(rows[0].id, null, "a listed-only built-in has no page");
  const claims = rows[3];
  assert.deepEqual([claims.description, claims.scope, claims.used, claims.status[0]], ["Explains claims", "Claims", 4, "Active"]);
  assert.deepEqual([rows[4].scope, rows[4].status[0], rows[4].defaultWorkflow], ["Global", "Draft", "Automatic"]);
});

test("search and the capability filter narrow the rows", () => {
  const rows = agentRows(AGENTS, OVERVIEW, []);
  assert.deepEqual(filterAgentRows(rows, "claims", "").map((row) => row.name), ["Claims helper"]);
  assert.deepEqual(filterAgentRows(rows, "", "deliver").map((row) => row.name), ["Coding agent"]);
});

test("only a selected agent that is in the loaded list opens its page", () => {
  const agents = [{ id: "a", name: "A" }];
  assert.equal(selectedListAgent(agents, "a")?.name, "A");
  assert.equal(selectedListAgent(agents, "stale-id"), undefined);
  assert.equal(selectedListAgent(agents, null), undefined);
  assert.equal(selectedListAgent(undefined, "a"), undefined);
});
