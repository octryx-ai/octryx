// Tab labels and icons of the Infrastructure admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const INFRASTRUCTURE_TAB_GROUP: AdminTabGroup = {
  label: "Infrastructure",
  tabs: [
    {
      id: "providers",
      label: "Providers",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      ),
    },
    {
      id: "modelsOverview",
      label: "Models overview",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 5h16v14H4zM4 10h16M10 10v9" />
        </svg>
      ),
    },
    {
      id: "modelCatalog",
      label: "Model catalog",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 6h16M4 12h16M4 18h10" />
        </svg>
      ),
    },
    {
      id: "modelOrder",
      label: "Default & fallback",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M7 4v16M4 17l3 3 3-3M14 6h6M14 12h4M14 18h2" />
        </svg>
      ),
    },
    {
      id: "corpIdentity",
      label: "Corp. Identity",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 5 6.5v5.5c0 4.8 2.9 7.9 7 9 4.1-1.1 7-4.2 7-9V6.5L12 3Z" />
          <path d="M9 12h6" />
          <path d="M12 9v6" />
        </svg>
      ),
    },
    {
      id: "branding",
      label: "Branding",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      ),
    },
    {
      id: "personality",
      label: "Personality",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3.5A8.5 8.5 0 0 1 20.5 12 8.5 8.5 0 0 1 12 20.5 8.5 8.5 0 0 1 3.5 12 8.5 8.5 0 0 1 12 3.5Z" />
          <path d="M9.5 11.5a2.5 2.5 0 1 0 0 0.1" />
          <path d="M14.5 11.5a2.5 2.5 0 1 0 0 0.1" />
          <path d="M16.8 15.5a4.8 4.8 0 0 1-9.6 0" />
        </svg>
      ),
    },
  ],
};
