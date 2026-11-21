// Tab labels and icons of the Channels & AI admin group.
import type { AdminTabGroup } from "./adminPanelTabs";

export const CHANNELS_AI_TAB_GROUP: AdminTabGroup = {
  label: "Channels & AI",
  tabs: [
    {
      id: "channels",
      label: "Channels",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      ),
    },
    {
      id: "mcp",
      label: "MCP Servers",
      icon: (
        <svg viewBox="0 0 24 24">
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
      ),
    },
    {
      id: "tts",
      label: "Voice & speech",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      ),
    },
    {
      id: "skills",
      label: "Skills",
      icon: (
        <svg viewBox="0 0 24 24">
          <path d="M12 3 5 6.5v5.5c0 4.8 2.9 7.9 7 9 4.1-1.1 7-4.2 7-9V6.5L12 3Z" />
          <path d="M9 12h6" />
          <path d="M12 9v6" />
        </svg>
      ),
    },
  ],
};
