export type WorkspaceArea =
  | "chat"
  | "knowledge"
  | "work"
  | "coding"
  | "agents"
  | "workflows"
  // Platform settings, runtime and automation.
  | "admin"
  // Live operations, runs, decisions and usage.
  | "operations"
  // My settings: personal pages, opened from the account menu, not a rail destination.
  | "personal"
  // The Setup guide (`?area=help&tab=setup`), opened from the account menu, the bell and the help panel.
  | "help";
