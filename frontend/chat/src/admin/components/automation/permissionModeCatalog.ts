// Run-mode choice for Automation targets. Actions and inbound webhooks store a run-mode key
// (`agent_type`), a label of how the run behaves; the shipped run modes come read-only from
// GET /admin/chat/api/panel/modes. The forms require an explicit visible choice and show a stored key that names no
// shipped run mode as such instead of rewriting it.

export const PERMISSION_MODES_ENDPOINT = "/admin/chat/api/panel/modes";

export type PermissionModeRow = {
  id?: string;
  key: string;
  name: string;
  is_active?: boolean;
  capability_type?: string;
};

export type PermissionModeCatalog =
  | { status: "loading"; modes: PermissionModeRow[] }
  | { status: "ready"; modes: PermissionModeRow[] }
  | { status: "error"; modes: PermissionModeRow[]; error: string };

export type PermissionModeChoiceState = "loading" | "error" | "empty" | "unchosen" | "invalid_stored" | "ready";

export type PermissionModeChoice = {
  state: PermissionModeChoiceState;
  // Active modes, the only ones offered.
  options: PermissionModeRow[];
  // The submitted value when it is not an active mode: shown as such, never rewritten.
  storedInvalid: { key: string; reason: "inactive" | "unknown" } | null;
  message: string | null;
  canSubmit: boolean;
};

function activeModes(modes: PermissionModeRow[]): PermissionModeRow[] {
  return modes.filter((mode) => mode.key && mode.is_active !== false);
}

export function permissionModeChoice(catalog: PermissionModeCatalog, value: string): PermissionModeChoice {
  const options = activeModes(catalog.modes);
  const key = value.trim();
  const blocked = (state: PermissionModeChoiceState, message: string, storedInvalid: PermissionModeChoice["storedInvalid"] = null) => ({
    state, options, storedInvalid, message, canSubmit: false,
  });
  if (catalog.status === "loading") return blocked("loading", "Loading run modes…");
  if (catalog.status === "error") return blocked("error", `Run modes could not be loaded: ${catalog.error}`);
  if (key && !options.some((mode) => mode.key === key)) {
    const known = catalog.modes.find((mode) => mode.key === key);
    return blocked(
      "invalid_stored",
      known
        ? `The saved run mode "${key}" is inactive. Choose one of the shipped run modes.`
        : `The saved run mode "${key}" no longer exists. Choose one of the shipped run modes.`,
      { key, reason: known ? "inactive" : "unknown" },
    );
  }
  if (!options.length) return blocked("empty", "No run mode is available.");
  if (!key) return blocked("unchosen", "Choose the run mode this automation runs with.");
  return { state: "ready", options, storedInvalid: null, message: null, canSubmit: true };
}
