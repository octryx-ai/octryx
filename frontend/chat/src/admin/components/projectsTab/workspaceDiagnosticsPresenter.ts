import type { ProjectSettingsTab } from "./projectSettingsSections";

// Translates workspace operating-model diagnostic codes
// (backend workspace_composition/admin_api.py) into impact and fix. The raw
// code stays visible in the UI as muted mono text for support.
export type WorkspaceDiagnosticInput = {
  code: string;
  severity: string;
  message: string;
};

export type WorkspaceDiagnosticView = {
  code: string;
  severity: string;
  title: string;
  impact: string;
  fix: string;
  fixSection: ProjectSettingsTab | null;
  fixLabel: string;
};

export function presentWorkspaceDiagnostic(
  warning: WorkspaceDiagnosticInput,
  runtimeAssignmentMode: string,
): WorkspaceDiagnosticView {
  const base = {
    code: warning.code,
    severity: warning.severity,
  };
  if (warning.code === "missing-runtime-binding") {
    const allInstalled = runtimeAssignmentMode !== "selected_only";
    return {
      ...base,
      title: "No runtime is pinned to this workspace",
      impact: allInstalled
        ? "Chats still run because the runtime access mode allows all installed runtimes, but no explicit runtime choice is recorded."
        : "Chats in this workspace cannot start: the access mode only allows selected runtimes and none is selected.",
      fix: "Choose the models under Models.",
      fixSection: "models",
      fixLabel: "Open models",
    };
  }
  if (warning.code === "missing-default-runtime") {
    return {
      ...base,
      title: "No default runtime is set",
      impact: "Runtimes are allowed, but none is marked as default, so the platform picks one per chat.",
      fix: "Choose a default model under Models.",
      fixSection: "models",
      fixLabel: "Open models",
    };
  }
  return {
    ...base,
    title: warning.message || warning.code,
    impact: warning.message,
    fix: "",
    fixSection: null,
    fixLabel: "",
  };
}
