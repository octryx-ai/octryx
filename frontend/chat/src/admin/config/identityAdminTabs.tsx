// Tab labels and icons of the Identity admin group (accounts, access, groups, sign-in).
import type { AdminTabGroup } from "./adminPanelTabs";

export const IDENTITY_TAB_GROUP: AdminTabGroup = {
  label: "Identity",
  tabs: [
    {
      id: "users",
      label: "User accounts",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
        </svg>
      ),
    },
    {
      id: "identityRoles",
      label: "Platform access",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 5 6.5v5.5c0 4.8 2.9 7.9 7 9 4.1-1.1 7-4.2 7-9V6.5L12 3Z" />
          <path d="M9 12h6" />
        </svg>
      ),
    },
    {
      id: "identityGroups",
      label: "Groups",
      icon: (
        <svg viewBox="0 0 24 24">
          <circle cx="8" cy="8" r="3" />
          <circle cx="17" cy="9" r="2.5" />
          <path d="M3 20c.8-3.5 3-5 5-5s4.2 1.5 5 5" />
          <path d="M13.5 19c.5-2.4 2-3.6 3.5-3.6 1.6 0 3.1 1.2 3.6 3.6" />
        </svg>
      ),
    },
    {
      id: "identityProviders",
      label: "Sign-in & SSO",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 12a4 4 0 0 1 4-4h4" />
          <path d="M12 16H8a4 4 0 0 1 0-8" />
          <path d="M12 8h4a4 4 0 0 1 0 8h-4" />
          <path d="M9 12h6" />
        </svg>
      ),
    },
    {
      id: "identityAccess",
      label: "Access check",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 4 7v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V7l-8-4Z" />
          <path d="M8 12h8" />
          <path d="M12 8v8" />
        </svg>
      ),
    },
  ],
};
