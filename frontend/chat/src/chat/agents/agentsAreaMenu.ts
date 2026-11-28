import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import type { AgentsNavKey } from "./AgentsAreaNav";

export type AgentsAreaEntry =
  | { host: "agents"; key: AgentsNavKey; label: string; group: string }
  | { host: "workflows"; tab: AdminTab; label: string; group: string };

export const AGENTS_AREA_ENTRIES: AgentsAreaEntry[] = [
  { host: "agents", key: "clients", label: "Connected clients", group: "Clients" },
  { host: "agents", key: "install", label: "Install octryx-claude", group: "Clients" },
  { host: "workflows", tab: "agents", label: "Agents", group: "Build" },
  { host: "workflows", tab: "workflowList", label: "Workflows", group: "Build" },
  { host: "workflows", tab: "skills", label: "Skills", group: "Build" },
  { host: "agents", key: "classification", label: "Seats & data classification", group: "Governance" },
  { host: "agents", key: "policy", label: "Policy", group: "Governance" },
  { host: "workflows", tab: "toolCatalog", label: "Tools", group: "Reference" },
];

export function agentsAreaGroup(key: string): string {
  return AGENTS_AREA_ENTRIES.find((entry) => entry.host === "agents" && entry.key === key)?.group ?? "";
}
