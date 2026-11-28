// Effective setup (backend `services/effective_setup`, `GET /api/v1/effective-setup`): what an octryx-claude session
// actually gets, part by part, each with its source, version and what enforces it. Pure parsing here; the page renders it.
import type { Enforcement } from "../awBadges";

export const EFFECTIVE_SETUP_PATH = "/api/v1/effective-setup";

export type SetupPart = {
  id: string;
  title: string;
  sourceLabel: string;
  sourceTab: string | null;
  version: string | null;
  enforced: Enforcement;
  tokens: number;
  details: Record<string, unknown>;
};

export type SetupBudgetGroup = { key: string; label: string; tokens: number };

export type EffectiveSetup = {
  capabilityClass: string;
  capabilitySource: string;
  workflowKey: string;
  profileStatus: string;
  profileReason: string;
  parts: SetupPart[];
  budget: { total: number; limit: number; groups: SetupBudgetGroup[] };
};

export type SetupOption = { id: string; label: string };

export type SetupOptions = {
  projects: SetupOption[];
  users: SetupOption[];
  agents: SetupOption[];
  workflows: { key: string; title: string; capability: string }[];
};

export type SetupQuery = {
  projectId: string;
  userId: string;
  agentId: string;
  workflowKey: string;
};

type Json = Record<string, unknown>;

const record = (value: unknown): Json => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

const ENFORCEMENTS: Enforcement[] = ["enforced", "guided", "guidance"];

export function readSetupPart(raw: unknown): SetupPart {
  const part = record(raw);
  const source = record(part.source);
  const enforced = ENFORCEMENTS.includes(part.enforced as Enforcement) ? (part.enforced as Enforcement) : "guidance";
  return {
    id: text(part.id),
    title: text(part.title),
    sourceLabel: text(source.label),
    sourceTab: text(source.tab) || null,
    version: text(part.version) || null,
    enforced,
    tokens: count(part.tokens),
    details: record(part.details),
  };
}

export function readEffectiveSetup(raw: unknown): EffectiveSetup {
  const body = record(raw);
  const summary = record(body.summary);
  const capability = record(summary.capability);
  const budget = record(body.budget);
  return {
    capabilityClass: text(capability.class),
    capabilitySource: text(capability.source),
    workflowKey: text(summary.workflow_key),
    profileStatus: text(summary.profile_status),
    profileReason: text(summary.profile_reason),
    parts: list(body.parts).map(readSetupPart),
    budget: {
      total: count(budget.total),
      limit: count(budget.limit),
      groups: list(budget.groups).map((item) => {
        const group = record(item);
        return { key: text(group.key), label: text(group.label), tokens: count(group.tokens) };
      }),
    },
  };
}

export function readSetupOptions(raw: unknown): SetupOptions {
  const body = record(raw);
  return {
    projects: list(body.projects).map((item) => ({ id: text(record(item).id), label: text(record(item).name) })),
    users: list(body.users).map((item) => ({ id: text(record(item).id), label: text(record(item).username) })),
    agents: list(body.agents).map((item) => ({ id: text(record(item).id), label: text(record(item).name) })),
    workflows: list(body.workflows).map((item) => ({
      key: text(record(item).key),
      title: text(record(item).title),
      capability: text(record(item).capability),
    })),
  };
}

export function setupQueryString(query: SetupQuery): string {
  const params = new URLSearchParams();
  if (query.projectId) params.set("project_id", query.projectId);
  if (query.userId) params.set("user_id", query.userId);
  if (query.agentId) params.set("agent_id", query.agentId);
  if (query.workflowKey) params.set("workflow_key", query.workflowKey);
  return params.toString();
}

/** The bar widths in percent of the turn budget (or of the total when no budget applies). */
export function budgetShares(budget: EffectiveSetup["budget"]): { key: string; label: string; tokens: number; percent: number }[] {
  const base = budget.limit > 0 ? budget.limit : Math.max(budget.total, 1);
  return budget.groups.map((group) => ({ ...group, percent: Math.min(100, (group.tokens / base) * 100) }));
}
