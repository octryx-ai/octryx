// Tab labels and icons of the Central configuration admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const CENTRAL_CONFIG_TAB_GROUP: AdminTabGroup = {
  // The Admin entries of the central configuration whose pages are still to come.
  label: "Central configuration",
  tabs: [
    {
      id: "adminProblems",
      label: "Problems",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 4 3 20h18L12 4Z" />
          <path d="M12 10v4" />
          <path d="M12 17h.01" />
        </svg>
      ),
    },
    {
      id: "adminConnections",
      label: "Connections",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M9 15l6-6" />
          <path d="M7 12l-2 2a3 3 0 0 0 4 4l2-2" />
          <path d="M17 12l2-2a3 3 0 0 0-4-4l-2 2" />
        </svg>
      ),
    },
    {
      id: "platformVersion",
      label: "Version",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 7h16v10H4z" />
          <path d="M8 11h8" />
          <path d="M8 14h5" />
        </svg>
      ),
    },
    {
      id: "platformDevices",
      label: "Devices",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 6h16v10H4z" />
          <path d="M2 19h20" />
        </svg>
      ),
    },
    {
      id: "plugins",
      label: "Plugins",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M9 3v4" />
          <path d="M15 3v4" />
          <path d="M6 7h12v4a6 6 0 0 1-12 0z" />
          <path d="M12 17v4" />
        </svg>
      ),
    },
  ],
};
