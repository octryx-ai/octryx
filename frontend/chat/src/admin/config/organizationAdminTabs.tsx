// Tab labels and icons of the Organization admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const ORGANIZATION_TAB_GROUP: AdminTabGroup = {
  label: "Organization",
  tabs: [
    {
      id: "projects",
      label: "Projects",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" />
          <path d="M12 12 21 7.5" />
          <path d="M12 12 3 7.5" />
          <path d="M12 12v9" />
        </svg>
      ),
    },
    {
      id: "backupRestore",
      label: "Backup & Restore",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 4h16v6H4z" />
          <path d="M6 14h12" />
          <path d="M8 18h8" />
          <path d="M12 10v8" />
        </svg>
      ),
    },
  ],
};
