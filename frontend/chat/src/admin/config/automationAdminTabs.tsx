// Tab labels and icons of the Automation admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const AUTOMATION_TAB_GROUP: AdminTabGroup = {
  label: "Automation",
  tabs: [
    {
      id: "connectors",
      label: "Connectors",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      ),
    },
    {
      id: "databases",
      label: "Databases",
      icon: (
        <svg viewBox="0 0 24 24">
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
        </svg>
      ),
    },
    {
      id: "toolCatalog",
      label: "Tool Catalog",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 6h16" />
          <path d="M4 12h16" />
          <path d="M4 18h16" />
          <circle cx="8" cy="6" r="1.5" />
          <circle cx="16" cy="12" r="1.5" />
          <circle cx="11" cy="18" r="1.5" />
        </svg>
      ),
    },
    {
      id: "scenarios",
      label: "Scenarios",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 6h16" />
          <path d="M4 12h10" />
          <path d="M4 18h16" />
          <circle cx="17" cy="12" r="3" />
        </svg>
      ),
    },
    {
      id: "workspaceKnowledge",
      label: "Workspace Knowledge",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 5h11a3 3 0 0 1 3 3v11H7a3 3 0 0 1-3-3V5Z" />
          <path d="M8 9h6M8 13h4" />
          <circle cx="18" cy="18" r="3" />
        </svg>
      ),
    },
    {
      id: "knowledge",
      label: "Knowledge",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 17A2.5 2.5 0 0 0 4 14.5V5a2 2 0 0 1 2-2h14v18H6a2 2 0 0 1-2-2v-.5" />
        </svg>
      ),
    },
    {
      id: "agents",
      label: "Agent Builder",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" />
          <path d="M8.5 10.5l3.5 2 3.5-2" />
          <path d="M12 12.5v4" />
        </svg>
      ),
      children: [
        {
          id: "agents",
          label: "Agents",
          icon: (
            <svg viewBox="0 0 24 24">
              <path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" />
              <path d="M8.5 10.5l3.5 2 3.5-2" />
              <path d="M12 12.5v4" />
            </svg>
          ),
        },
        {
          id: "effectiveSetup",
          label: "Effective setup",
          icon: (
            <svg viewBox="0 0 24 24">
              <path d="M3 6h18M3 12h18M3 18h12" />
            </svg>
          ),
        },
        {
          id: "workflowList",
          label: "Workflows",
          icon: (
            <svg viewBox="0 0 24 24">
              <circle cx="5" cy="6" r="2" />
              <circle cx="5" cy="18" r="2" />
              <circle cx="19" cy="12" r="2" />
              <path d="M7 6h4l6 6M7 18h4l6-6" />
            </svg>
          ),
        },
        {
          id: "workflowChecks",
          label: "Check results",
          icon: (
            <svg viewBox="0 0 24 24">
              <path d="M12 3 5 6.5v5.5c0 4.8 2.9 7.9 7 9 4.1-1.1 7-4.2 7-9V6.5L12 3Z" />
              <path d="m9.5 12 2 2 4-5" />
            </svg>
          ),
        },
        {
          id: "workflowDesigner",
          label: "Workflow designer",
          icon: (
            <svg viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="5" rx="1" />
              <rect x="14" y="16" width="7" height="5" rx="1" />
              <path d="M6.5 8v4.5h11V16" />
            </svg>
          ),
        },
        {
          id: "promptCatalog",
          label: "System prompt texts",
          icon: (
            <svg viewBox="0 0 24 24">
              <path d="M6 3h9l3 3v15H6z" />
              <path d="M15 3v3h3" />
              <path d="M9 11h6" />
              <path d="M9 15h4" />
            </svg>
          ),
        },
        {
          id: "instructions",
          label: "Instructions",
          icon: (
            <svg viewBox="0 0 24 24">
              <path d="M4 5h16v10H8l-4 4z" />
              <path d="M8 9h8" />
              <path d="M8 13h5" />
            </svg>
          ),
        },
      ],
    },
    {
      id: "schedulers",
      label: "Schedulers",
      icon: (
        <svg viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <path d="M16 2v4M8 2v4M3 10h18" />
        </svg>
      ),
    },
    {
      id: "tasks",
      label: "Actions",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M9 11l3 3L22 4" />
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>
      ),
    },
    {
      id: "webhooks",
      label: "Webhooks",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      ),
    },
  ],
};
