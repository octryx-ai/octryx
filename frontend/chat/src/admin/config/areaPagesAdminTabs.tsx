// Tab labels and icons of the area pages reached from the admin panel.
import type { AdminTabGroup } from "./adminPanelTabs";

export const AREA_PAGES_TAB_GROUP: AdminTabGroup = {
  label: "Area pages",
  tabs: [
    {
      id: "knowledgeLibrary",
      label: "Search",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="11" cy="11" r="6" />
          <path d="m20 20-4.2-4.2" />
        </svg>
      ),
    },
    {
      id: "knowledgeSources",
      label: "Documents",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M6 3h9l4 4v14H6z" />
          <path d="M15 3v4h4" />
          <path d="M9 12h6M9 16h4" />
        </svg>
      ),
    },
    {
      id: "knowledgeResearch",
      label: "Research websites",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
      ),
    },
    {
      id: "knowledgeRelationships",
      label: "Explore",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="6" cy="12" r="2.5" />
          <circle cx="18" cy="6" r="2.5" />
          <circle cx="18" cy="18" r="2.5" />
          <path d="M8.3 11 15.7 7M8.3 13l7.4 4" />
        </svg>
      ),
    },
    {
      id: "knowledgeGraph",
      label: "Explore",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="5" cy="5" r="2" />
          <circle cx="19" cy="7" r="2" />
          <circle cx="12" cy="12" r="2.5" />
          <circle cx="6" cy="19" r="2" />
          <circle cx="18" cy="19" r="2" />
          <path d="M6.5 6.5l3.8 3.8M17.2 8l-3.4 2.6M10.4 13.8 7.3 17.4M13.8 13.8l2.9 3.6" />
        </svg>
      ),
    },
    {
      id: "runtimePolicyLists",
      label: "Policy lists",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
          <circle cx="16" cy="7" r="2" />
          <circle cx="10" cy="17" r="2" />
        </svg>
      ),
    },
    {
      id: "runtimeExecution",
      label: "Execution & storage",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="12" rx="2" />
          <path d="m7 9 3 2-3 2M12 13h4" />
          <path d="M8 20h8" />
        </svg>
      ),
    },
    {
      id: "commandSafety",
      label: "Command safety",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="m7 9 3 3-3 3M13 15h4" />
        </svg>
      ),
    },
    {
      id: "contentSecurity",
      label: "Content security",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M5 4h10l4 4v12H5z" />
          <path d="M9 13h6M9 17h3" />
        </svg>
      ),
    },
    {
      id: "approvalRule",
      label: "Approval rule",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="9" cy="8" r="3" />
          <path d="M3 19c0-3 2.7-5 6-5s6 2 6 5" />
          <path d="m15 11 2 2 4-4" />
        </svg>
      ),
    },
    {
      id: "classificationPolicy",
      label: "Classification",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 10h18M9 4v16" />
        </svg>
      ),
    },
    {
      id: "cedarPolicies",
      label: "Policies",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      ),
    },
    {
      id: "policyTestBench",
      label: "Policy test bench",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" />
        </svg>
      ),
    },
    {
      id: "runtimeLimits",
      label: "Limits & budgets",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 18a8 8 0 1 1 16 0" />
          <path d="m12 18 4-6" />
        </svg>
      ),
    },
    {
      id: "runtimeCompression",
      label: "Tool output compression",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5" />
        </svg>
      ),
    },
  ],
};
