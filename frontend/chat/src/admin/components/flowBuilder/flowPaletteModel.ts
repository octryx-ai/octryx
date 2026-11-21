// Pure model of the workflow palette: entries and groups from the node catalog (or the node
// registry), the "Agents" group from the caller's agent list, search, default collapse and the
// availability of every entry. No authorization is decided here: catalog entries keep the
// availability the server computed (policy-gated tools stay disabled with the server's reason),
// and agents apply the agent's own active flag and workspace scope.
import type { FlowNodeCatalogItem, FlowNodeContract, FlowNodeType } from "./flowBuilderTypes";

export type FlowAgentOption = {
  id: string;
  name: string;
  goal?: string;
  stepCount?: number;
  isActive?: boolean;
  projectId?: string;
  disabledReason?: string | null;
};

export type PaletteEntry = {
  key: string;
  type: FlowNodeType;
  label: string;
  iconHint: string;
  meta?: string;
  description?: string;
  agentId?: string;
  contract?: FlowNodeContract;
  catalogItem?: FlowNodeCatalogItem;
  disabledReason?: string | null;
  // Extra search words (never shown), e.g. the plain names of the If / else step.
  keywords?: string;
};

export type PaletteGroup = { label: string; entries: PaletteEntry[] };

export const AGENTS_GROUP = "Agents";
const AI_GROUP = "AI";
// Open on first use: the start/end of a workflow, the AI steps including the agents, and the
// logic steps, so If / else is visible without knowing where to look.
const DEFAULT_OPEN_GROUPS = new Set(["input / output", "ai", "agents", "triggers", "output", "logic"]);

// The conditional step (node type "router") in plain words. Its technical name from the catalog
// stays in the secondary text and in search, so "router" still finds it.
const IF_ELSE_LABEL = "If / else";
const IF_ELSE_DESCRIPTION =
  "Checks rules from top to bottom and continues on the branch of the first match, otherwise on the Otherwise branch.";
const IF_ELSE_KEYWORDS = "if else elseif condition conditional branch branching gateway decision router route";

function presentEntry(entry: PaletteEntry): PaletteEntry {
  if (entry.type !== "router" || entry.agentId) return entry;
  const technical = entry.label && entry.label !== IF_ELSE_LABEL ? entry.label : "Router";
  return {
    ...entry,
    label: IF_ELSE_LABEL,
    meta: entry.meta ? `${technical} · ${entry.meta}` : technical,
    description: IF_ELSE_DESCRIPTION,
    keywords: [IF_ELSE_KEYWORDS, technical, entry.description].filter(Boolean).join(" "),
  };
}

const STATIC_GROUPS: Array<{ label: string; nodes: Array<[FlowNodeType, string]> }> = [
  { label: "Triggers", nodes: [["trigger", "Manual"], ["trigger", "Scheduler"], ["trigger", "Webhook"]] },
  { label: "Logic", nodes: [["router", "Router"], ["parallel", "Parallel"], ["join", "Join"], ["supervisor", "Supervisor"]] },
  { label: "Tools", nodes: [["tool_step", "Tool call"], ["retrieval", "Retrieval"]] },
  {
    label: "Gates",
    nodes: [["policy_gate", "Policy gate"], ["clarification_gate", "Clarification gate"], ["approval", "Human approval"], ["evaluation", "Evaluation gate"]],
  },
  { label: "Output", nodes: [["output", "Final output"]] },
];

export function agentDisabledReason(
  agent: Pick<FlowAgentOption, "isActive" | "projectId">,
  flowProjectId: string | null,
  projectNameById: Map<string, string>,
): string | null {
  if (agent.isActive === false) return "Inactive — activate it on its agent page";
  const agentProject = agent.projectId || "";
  if (!agentProject || agentProject === (flowProjectId || "")) return null;
  const agentWorkspace = projectNameById.get(agentProject) ?? "another workspace";
  const flowWorkspace = flowProjectId ? projectNameById.get(flowProjectId) ?? "another workspace" : "Global";
  return flowProjectId
    ? `Belongs to ${agentWorkspace}; this workflow is in ${flowWorkspace}`
    : `Belongs to ${agentWorkspace}; this workflow is Global`;
}

// Maps the agent panel payload (camelCase) and attaches the availability reason.
export function flowAgentOptions(
  rows: Array<Record<string, unknown>>,
  flowProjectId: string | null,
  projectNameById: Map<string, string>,
): FlowAgentOption[] {
  return rows
    .filter((row) => typeof row.id === "string" && row.id)
    .map((row) => {
      const agent: FlowAgentOption = {
        id: String(row.id),
        name: String(row.name || row.id),
        goal: typeof row.goal === "string" ? row.goal : undefined,
        stepCount: Array.isArray(row.steps) ? row.steps.length : 0,
        isActive: typeof row.isActive === "boolean" ? row.isActive : typeof row.is_active === "boolean" ? row.is_active : undefined,
        projectId: String(row.projectId ?? row.project_id ?? ""),
      };
      return { ...agent, disabledReason: agentDisabledReason(agent, flowProjectId, projectNameById) };
    });
}

function catalogEntry(item: FlowNodeCatalogItem): PaletteEntry {
  const disabled = item.availability_status === "disabled";
  return {
    key: `catalog:${item.id}`,
    type: item.node_type,
    label: item.display_name,
    iconHint: item.icon_hint || item.node_type,
    meta: `${item.binding_type} · ${item.token_cost_risk} cost`,
    description: item.description,
    catalogItem: item,
    disabledReason: disabled ? item.disabled_reason || `${item.display_name} is not available` : null,
  };
}

function agentEntry(agent: FlowAgentOption): PaletteEntry {
  return {
    key: `agent:${agent.id}`,
    type: "agent_step",
    label: agent.name,
    iconHint: "agent_step",
    meta: "Agent step",
    description: agent.goal,
    agentId: agent.id,
    disabledReason: agent.disabledReason ?? null,
  };
}

function pushEntry(groups: Map<string, PaletteGroup>, label: string, entry: PaletteEntry) {
  const group = groups.get(label) ?? { label, entries: [] };
  group.entries.push(presentEntry(entry));
  groups.set(label, group);
}

export function buildPaletteGroups(
  catalogItems: FlowNodeCatalogItem[],
  contracts: FlowNodeContract[],
  agents: FlowAgentOption[],
): PaletteGroup[] {
  const groups = new Map<string, PaletteGroup>();
  if (catalogItems.length) {
    for (const item of catalogItems) pushEntry(groups, item.category, catalogEntry(item));
  } else if (contracts.length) {
    for (const contract of contracts) {
      pushEntry(groups, contract.category, {
        key: `contract:${contract.type}`, type: contract.type, label: contract.display_name,
        iconHint: contract.type, description: contract.description, contract,
      });
    }
  } else {
    for (const group of STATIC_GROUPS) {
      for (const [type, label] of group.nodes) pushEntry(groups, group.label, { key: `static:${type}:${label}`, type, label, iconHint: type });
    }
  }
  const ordered = [...groups.values()];
  if (agents.length) {
    // Agents sit right after the AI group (or first, when there is none): choosing an agent
    // by name is the main way to put AI into a workflow.
    const agentsGroup = { label: AGENTS_GROUP, entries: agents.map(agentEntry) };
    const aiIndex = ordered.findIndex((group) => group.label.toLowerCase() === AI_GROUP.toLowerCase());
    ordered.splice(aiIndex + 1, 0, agentsGroup);
  }
  return ordered;
}

export function defaultOpenGroups(groups: PaletteGroup[]): Set<string> {
  return new Set(groups.filter((group) => DEFAULT_OPEN_GROUPS.has(group.label.toLowerCase())).map((group) => group.label));
}

function entryHaystack(entry: PaletteEntry, groupLabel: string): string {
  return [entry.label, entry.meta, entry.description, entry.keywords, entry.catalogItem?.binding_ref, entry.type, groupLabel]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

// Every whitespace-separated term must match; groups without a match disappear.
export function filterPaletteGroups(groups: PaletteGroup[], query: string): PaletteGroup[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return groups;
  return groups
    .map((group) => ({
      ...group,
      entries: group.entries.filter((entry) => {
        const haystack = entryHaystack(entry, group.label);
        return terms.every((term) => haystack.includes(term));
      }),
    }))
    .filter((group) => group.entries.length > 0);
}

// While searching every matching group is shown open; otherwise the user's open set applies.
export function isPaletteGroupOpen(label: string, openGroups: Set<string>, query: string): boolean {
  return Boolean(query.trim()) || openGroups.has(label);
}

export function paletteEntryAccessibleName(entry: PaletteEntry): string {
  const what = entry.agentId ? `agent step: ${entry.label}` : entry.label;
  return entry.disabledReason ? `${what} — unavailable: ${entry.disabledReason}` : `Add ${what}`;
}
