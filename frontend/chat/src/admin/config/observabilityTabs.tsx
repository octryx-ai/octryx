import type { AdminTabGroup } from "./adminPanelTabs";

// Tab labels and icons of the Observability area (WP observability audit; icons from the approved
// mock). The area's navigation lives in adminPanelAreas.ts; this file only joins icons to the page ids.
export const OBSERVABILITY_TAB_GROUP: AdminTabGroup = {
  label: "Observability",
  tabs: [
    {
      id: "observabilityOverview",
      label: "Overview",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="4" y="4" width="7" height="7" rx="1.5" />
          <rect x="13" y="4" width="7" height="7" rx="1.5" />
          <rect x="4" y="13" width="7" height="7" rx="1.5" />
          <rect x="13" y="13" width="7" height="7" rx="1.5" />
        </svg>
      ),
    },
    {
      id: "operationsLive",
      label: "Live",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="2" />
          <path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8" />
        </svg>
      ),
    },
    {
      id: "operationsCosts",
      label: "Costs",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 20h16" />
          <path d="M7 16v-4M12 16V8M17 16v-7" />
        </svg>
      ),
    },
    {
      id: "observabilityHealth",
      label: "Health",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M3 12h4l2-5 4 10 2-5h6" />
        </svg>
      ),
    },
    {
      id: "observabilityRuns",
      label: "Runs",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M5 5h14M5 12h14M5 19h9" />
        </svg>
      ),
    },
    {
      id: "observabilityDecisions",
      label: "Decisions",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      ),
    },
    {
      id: "observabilityAudit",
      label: "Audit log",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M6 3h9l3 3v15H6z" />
          <path d="M9 10h6M9 14h6M9 18h3" />
        </svg>
      ),
    },
    {
      id: "usage",
      label: "Usage & costs",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="12" width="4" height="9" />
          <rect x="10" y="7" width="4" height="14" />
          <rect x="17" y="3" width="4" height="18" />
        </svg>
      ),
    },
    {
      id: "approvalDetail",
      label: "Approval",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 4 7v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V7l-8-4Z" />
          <path d="M9.5 12.5 11 14l3.5-4" />
        </svg>
      ),
    },
  ],
};
