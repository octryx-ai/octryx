// Sections of a Workspace's settings page: one flat section nav. Alias section ids resolve through SECTION_ALIASES
// (deep links, diagnostics fixes).
export type ProjectSettingsTab =
  | "overview"
  | "access"
  | "roles"
  | "plugins"
  | "models"
  | "coding"
  | "connectors"
  | "knowledge"
  | "repositories"
  | "agents"
  | "rules"
  | "observability"
  | "voice"
  | "diagnostics";

export type ProjectSettingsSection = {
  key: ProjectSettingsTab;
  label: string;
};

export const PROJECT_SETTINGS_SECTIONS: ProjectSettingsSection[] = [
  { key: "overview", label: "Overview" },
  { key: "access", label: "Access" },
  { key: "roles", label: "Roles" },
  { key: "plugins", label: "Plugins" },
  { key: "models", label: "Models" },
  { key: "coding", label: "Coding tools & devices" },
  { key: "connectors", label: "Connectors" },
  { key: "knowledge", label: "Knowledge" },
  { key: "repositories", label: "Repositories" },
  { key: "agents", label: "Agents & skills" },
  { key: "rules", label: "Rules" },
  { key: "observability", label: "Observability" },
  { key: "voice", label: "Voice" },
  { key: "diagnostics", label: "Diagnostics" },
];

// The twelve sections in one row did not fit at 1280 (Voice and Diagnostics off-screen). They are
// grouped: the groups are the page's segments, a group with several sections shows them as a second, small row.
export type ProjectSettingsGroup = { key: string; label: string; sections: ProjectSettingsTab[] };

export const PROJECT_SETTINGS_GROUPS: ProjectSettingsGroup[] = [
  { key: "general", label: "Overview", sections: ["overview", "diagnostics"] },
  // Plugins: switching the image's plugins on in this Workspace sits next to who may do what.
  { key: "access", label: "Access", sections: ["access", "roles", "plugins"] },
  { key: "ai", label: "Models & agents", sections: ["models", "agents", "coding", "voice"] },
  { key: "data", label: "Data", sections: ["connectors", "knowledge", "repositories"] },
  { key: "rules", label: "Rules & monitoring", sections: ["rules", "observability"] },
];

export function projectSettingsGroupOf(section: ProjectSettingsTab): ProjectSettingsGroup {
  return PROJECT_SETTINGS_GROUPS.find((group) => group.sections.includes(section)) ?? PROJECT_SETTINGS_GROUPS[0];
}

// Card addresses: a link may name a card instead of its section (`workspaceSectionHref`); the "Documentation target"
// card (feature_documentation) sits in Knowledge, the seat card (`classification`) in Rules.
export const SECTION_ALIASES: Record<string, ProjectSettingsTab> = {
  classification: "rules",
  documentation: "knowledge",
};

export function resolveProjectSettingsTab(value: string): ProjectSettingsTab | null {
  if (PROJECT_SETTINGS_SECTIONS.some((section) => section.key === value)) return value as ProjectSettingsTab;
  return SECTION_ALIASES[value] ?? null;
}

export function projectSettingsSectionLabel(key: ProjectSettingsTab): string {
  return PROJECT_SETTINGS_SECTIONS.find((section) => section.key === key)?.label || key;
}
