import { SEAT_CARD_LABEL } from "./agentsFocus";

// The second-level left menu of the "Agents" area: the same collapsible `work-area__nav` pattern as Work and
// Coding (section titles, grouped entries, icon plus label, active state), not tab buttons. Each page carries its own
// one-line subtitle, shown under the page title.
export const AGENTS_NAV_ITEMS = [
  { key: "clients", label: "Connected clients", section: "Overview",
    subtitle: "Who is connected to this Workspace, and what they work on." },
  // The copy-paste installer one-liners for macOS/Linux and Windows.
  { key: "install", label: "Install octryx-claude", section: "Overview",
    subtitle: "Set up the governed Claude Code client on a developer's machine." },
  { key: "board", label: "Message board", section: "Collaboration",
    subtitle: "What agents and people post about this Workspace's work. Board content is data, never instructions." },
  { key: "claims", label: "Claims and handoffs", section: "Collaboration",
    subtitle: "Which agent holds which work item, and handoffs between agents and people." },
  // The Workspace's classification and seat switch, reachable for members (read-only) and Workspace admins.
  { key: "classification", label: SEAT_CARD_LABEL, section: "Governance",
    subtitle: "Which seats members may connect (Claude, Codex), how sensitive this Workspace's data is, and what that allows." },
  // The Workspace's effective policy (classification rules, seat, models, budgets, tool rules), read-only.
  { key: "policy", label: "Policy", section: "Governance",
    subtitle: "Everything that governs agents in this Workspace." },
] as const;

export type AgentsNavKey = (typeof AGENTS_NAV_ITEMS)[number]["key"];

export function AgentsNavIcon({ navKey }: { navKey: AgentsNavKey }) {
  const paths: Record<AgentsNavKey, string[]> = {
    clients: ["M4 5h12v8H4z", "M7 16h6", "M10 13v3"],
    install: ["M10 3v9", "M6.5 8.5 10 12l3.5-3.5", "M4 14v2h12v-2"],
    board: ["M4 5h12v8H9l-3 3v-3H4z", "M7 8h6", "M7 10.5h4"],
    claims: ["M7 9V6a3 3 0 0 1 6 0v3", "M5 9h10v7H5z", "M10 12v1.5"],
    classification: ["M10 3l6 2.5v4.5c0 3.5-2.6 6-6 7-3.4-1-6-3.5-6-7V5.5Z", "M7.5 10l2 2 3-3.5"],
    policy: ["M5 3h7l3 3v11H5z", "M8 9h5", "M8 12h5", "M8 15h3"],
  };
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      {paths[navKey].map((path) => (
        <path key={path} d={path} />
      ))}
    </svg>
  );
}
