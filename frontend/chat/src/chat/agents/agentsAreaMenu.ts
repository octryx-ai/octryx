import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import type { AgentsNavKey } from "./AgentsAreaNav";

// One Agents area: Agents (clients, collaboration, the Workspace's rules)
// and Agents & workflows (the builder) are one area with one menu, Clients · Build · Rules · Reference. Each entry
// still opens its page where it lives: the Agents pages in the Agents component (`agents_view`), the builder pages
// in the admin shell (`area=workflows`, `tab`).
export type AgentsAreaEntry =
  | { host: "agents"; key: AgentsNavKey; label: string; group: string }
  | { host: "workflows"; tab: AdminTab; label: string; group: string };

export const AGENTS_AREA_ENTRIES: AgentsAreaEntry[] = [
  { host: "agents", key: "clients", label: "Connected clients", group: "Clients" },
  { host: "agents", key: "install", label: "Install octryx-claude", group: "Clients" },
  // The Message board and Claims & handoffs left the navigation (the companion shows jobs, questions and
  // handovers; octryx-claude keeps using the backend). Their links still open them.
  { host: "workflows", tab: "agents", label: "Agents", group: "Build" },
  { host: "workflows", tab: "workflowList", label: "Workflows", group: "Build" },
  { host: "workflows", tab: "skills", label: "Skills", group: "Build" },
  // Seat-card finding: admins look for "seats"; the Workspace's seat card and its effective policy are
  // back in the menu, for the Workspace in focus (members see them read-only). Instructions and Effective setup stay
  // under Admin › Rules.
  { host: "agents", key: "classification", label: "Seats & data classification", group: "Governance" },
  { host: "agents", key: "policy", label: "Policy", group: "Governance" },
  { host: "workflows", tab: "toolCatalog", label: "Tools", group: "Reference" },
];

/** The menu group of an Agents page (`agents_view`), e.g. "Clients". */
export function agentsAreaGroup(key: string): string {
  return AGENTS_AREA_ENTRIES.find((entry) => entry.host === "agents" && entry.key === key)?.group ?? "";
}
