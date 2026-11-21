// Cedar policy engine model: the test bench (entities, resource fields, the request, the result, saved cases).
import { isRecord, str, strs, type Json } from "./policyEngineValues";

export type BenchEntities = {
  workspaces: { id: string; name: string; classification: string }[];
  users: { id: string; name: string }[];
  tools: string[];
  modelAliases: string[];
  actions: string[];
  dataPolicyClasses: string[];
};

export function readEntities(raw: unknown): BenchEntities {
  const value = isRecord(raw) ? raw : {};
  const list = (key: string) => (Array.isArray(value[key]) ? (value[key] as unknown[]).filter(isRecord) : []);
  return {
    workspaces: list("workspaces").map((item) => ({ id: str(item.id), name: str(item.name) || str(item.id), classification: str(item.classification) })),
    users: list("users").map((item) => ({ id: str(item.id), name: str(item.display_name) || str(item.username) || str(item.id) })),
    tools: strs(value.tools),
    modelAliases: strs(value.model_aliases),
    actions: strs(value.actions),
    dataPolicyClasses: strs(value.data_policy_classes),
  };
}

/** Which resource field an action asks for in the test bench. */
export type ResourceField = "none" | "alias" | "data_policy_class" | "tool" | "command" | "path";
export function resourceField(action: string): ResourceField {
  if (action === "call_model") return "alias";
  if (action === "use_reranker" || action === "use_remote_embeddings") return "data_policy_class";
  if (action === "call_tool" || action === "read_connector" || action === "write_connector") return "tool";
  if (action === "run_command") return "command";
  if (action === "read_path" || action === "write_path") return "path";
  return "none";
}

/** `connection`: the named-connection id a connector tool call would run on (optional, `context.connections`). */
export type BenchForm = { workspaceId: string; userId: string; action: string; value: string; tool: string; params: string; connection?: string };

/** The bench request; `null` with a reason when the form is incomplete. */
export function benchRequest(form: BenchForm): { request: Json | null; problem: string | null } {
  if (!form.workspaceId) return { request: null, problem: "Pick a Workspace." };
  if (!form.action) return { request: null, problem: "Pick an action." };
  const field = resourceField(form.action);
  const resource: Json = {};
  if (field === "tool") {
    if (!form.tool) return { request: null, problem: "Pick a tool." };
    resource.tool = form.tool;
    if (form.connection) resource.connections = [form.connection];
    if (form.params.trim()) {
      try {
        const parsed = JSON.parse(form.params);
        if (!isRecord(parsed)) return { request: null, problem: "Tool arguments must be a JSON object." };
        resource.params = parsed;
      } catch {
        return { request: null, problem: "Tool arguments must be valid JSON." };
      }
    }
  } else if (field === "path") {
    if (!form.value.trim()) return { request: null, problem: "Enter a path." };
    resource.path = form.value.trim();
    resource.tool = form.tool || (form.action === "write_path" ? "Edit" : "Read");
  } else if (field !== "none") {
    if (field !== "alias" && !form.value.trim()) return { request: null, problem: "Fill in the resource." };
    resource[field] = form.value;
  }
  return {
    request: { workspace_id: form.workspaceId, user_id: form.userId || null, action: form.action, resource },
    problem: null,
  };
}

export type BenchResult = {
  decision: string;
  action: string;
  principal: string;
  resource: string;
  determining: { id: string; source: string; text: string }[];
  errors: string[];
  legacy: { decision: string; reason: string } | null;
  policySource: string;
  notes: string[];
};

export function readBenchResult(raw: unknown): BenchResult | null {
  if (!isRecord(raw) || !str(raw.decision)) return null;
  const legacy = isRecord(raw.legacy) ? { decision: str(raw.legacy.decision), reason: str(raw.legacy.reason) } : null;
  return {
    decision: str(raw.decision),
    action: str(raw.action),
    principal: str(raw.principal),
    resource: str(raw.resource),
    determining: (Array.isArray(raw.determining) ? raw.determining : []).filter(isRecord).map((item) => ({
      id: str(item.id), source: str(item.source), text: str(item.text),
    })),
    errors: strs(raw.errors),
    legacy,
    policySource: str(raw.policy_source),
    notes: strs(raw.notes),
  };
}

export type TestCase = { id: string; name: string; expected: string; request: Json; createdBy: string };

export function readTestCases(raw: unknown): TestCase[] {
  const items = isRecord(raw) && Array.isArray(raw.items) ? raw.items : [];
  return items.filter(isRecord).map((item) => ({
    id: str(item.id),
    name: str(item.name),
    expected: str(item.expected),
    request: isRecord(item.request) ? item.request : {},
    createdBy: str(item.created_by),
  }));
}

/** "Bash (read) on Workspace X" style label of a saved request. */
export function testCaseLabel(testCase: TestCase): string {
  const resource = isRecord(testCase.request.resource) ? testCase.request.resource : {};
  const detail = Object.values(resource).filter((value) => typeof value === "string" && value).join(" ");
  return `${str(testCase.request.action)}${detail ? `: ${detail}` : ""} → expect ${testCase.expected}`;
}
