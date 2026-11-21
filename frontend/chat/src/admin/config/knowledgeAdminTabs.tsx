import type { AdminTabGroup } from "./adminPanelTabs";

// Tab labels and icons of Admin › Knowledge. The navigation lives in adminPanelAreas.ts; this file only
// joins icons to the page ids, like observabilityTabs.tsx.
export const KNOWLEDGE_ADMIN_TAB_GROUP: AdminTabGroup = {
  label: "Knowledge",
  tabs: [
    {
      id: "knowledgePackages",
      label: "Packages",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 4 7v10l8 4 8-4V7l-8-4Z" />
          <path d="M4 7l8 4 8-4M12 11v10" />
        </svg>
      ),
    },
    {
      id: "knowledgeBindings",
      label: "Bindings",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
          <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
        </svg>
      ),
    },
    {
      id: "knowledgeChanges",
      label: "Changes",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 7h12l-3-3M20 17H8l3 3" />
        </svg>
      ),
    },
    {
      id: "knowledgeHandbook",
      label: "Structured graph",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 5h7v14H4zM13 5h7v14h-7z" />
          <path d="M6.5 9h2M15.5 9h2M15.5 13h2" />
        </svg>
      ),
    },
    {
      id: "knowledgeMemory",
      label: "Memory",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
        </svg>
      ),
    },
    {
      id: "knowledgeEpisodes",
      label: "Episodes",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v4l3 2" />
        </svg>
      ),
    },
  ],
};
