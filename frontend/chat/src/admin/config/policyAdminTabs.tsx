// Tab labels and icons of the Policy admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const POLICY_TAB_GROUP: AdminTabGroup = {
  label: "Policy",
  tabs: [
    {
      id: "policies",
      label: "Policies",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 7h16" />
          <path d="M4 12h12" />
          <path d="M4 17h16" />
          <circle cx="18" cy="12" r="2.5" />
        </svg>
      ),
    },
    {
      id: "researchPolicies",
      label: "Research Policies",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 5h10" />
          <path d="M4 10h16" />
          <path d="M4 15h9" />
          <path d="M15 14l2 2 4-5" />
          <path d="M4 20h13" />
        </svg>
      ),
    },
  ],
};
