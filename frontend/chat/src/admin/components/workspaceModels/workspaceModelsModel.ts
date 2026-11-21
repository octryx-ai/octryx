// Workspace → Models. Pure: reads
// `/api/v1/admin/workspaces/{id}/models` (backend services/workspace_models) and builds the contract to save.

export type Seat = { mode: "allowed" | "forbidden"; subscription_models: string[]; company_models_in_seat: boolean };
export type Contract = { mode: "all_cleared" | "selected"; selected: string[]; default: string | null; task_overrides: Record<string, string>; seat: Seat };
export type ModelRow = {
  key: string; label: string; provider: string; gateway: boolean; clearedUpTo: string | null; approvedFor: string[];
  temperature: number | null; cleared: boolean; reason: string; usedIn: string[]; allowed: boolean;
};
export type TaskRow = { key: string; label: string; platformModel: string | null };
export type WorkspaceModels = {
  contract: Contract; models: ModelRow[]; tasks: TaskRow[]; level: string | null; seatAllowedAtLevel: boolean; companyModelAllowed: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.map((item) => String(item)) : []);

export function readWorkspaceModels(payload: unknown): WorkspaceModels | null {
  if (!isRecord(payload) || !isRecord(payload.contract)) return null;
  const contract = payload.contract;
  const seat = isRecord(contract.seat) ? contract.seat : {};
  const checks = isRecord(payload.seat_checks) ? payload.seat_checks : {};
  return {
    contract: {
      mode: contract.mode === "selected" ? "selected" : "all_cleared",
      selected: strings(contract.selected),
      default: text(contract.default) || null,
      task_overrides: isRecord(contract.task_overrides)
        ? Object.fromEntries(Object.entries(contract.task_overrides).filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== ""))
        : {},
      seat: { mode: seat.mode === "allowed" ? "allowed" : "forbidden", subscription_models: strings(seat.subscription_models),
        company_models_in_seat: seat.company_models_in_seat === true },
    },
    models: (Array.isArray(payload.models) ? payload.models : []).filter(isRecord).map((row) => ({
      key: text(row.key), label: text(row.label) || text(row.key), provider: text(row.provider), gateway: row.gateway === true,
      clearedUpTo: text(row.cleared_up_to) || null, approvedFor: strings(row.approved_for),
      temperature: typeof row.temperature === "number" ? row.temperature : null, cleared: row.cleared === true,
      reason: text(row.reason), usedIn: strings(row.used_in), allowed: row.allowed === true,
    })),
    tasks: (Array.isArray(payload.tasks) ? payload.tasks : []).filter(isRecord).map((row) => ({
      key: text(row.key), label: text(row.label) || text(row.key), platformModel: text(row.platform_model) || null,
    })),
    level: text(payload.level) || null,
    seatAllowedAtLevel: checks.seat_allowed_at_level === true,
    companyModelAllowed: checks.company_model_allowed === true,
  };
}

export const USED_IN_TEXT: Record<string, string> = { chat: "Chat & agents", coding_tools: "Coding tools", device_runs: "Device runs" };

/** Whether a model is allowed under the draft contract. */
export function isAllowed(contract: Contract, row: ModelRow): boolean {
  return row.cleared && (contract.mode === "all_cleared" || contract.selected.includes(row.key));
}

export function toggleModel(contract: Contract, key: string, on: boolean): Contract {
  const selected = on ? [...new Set([...contract.selected, key])] : contract.selected.filter((item) => item !== key);
  // A task model that is no longer allowed falls back to the platform's (the server would refuse it).
  const task_overrides = on ? contract.task_overrides
    : Object.fromEntries(Object.entries(contract.task_overrides).filter(([, model]) => model !== key));
  return { ...contract, selected, task_overrides, default: contract.default && !on && contract.default === key ? null : contract.default };
}

/** Set (``key``) or clear (``""``: the platform's task model) the Workspace's model for one background task. */
export function setTaskModel(contract: Contract, task: string, key: string): Contract {
  const task_overrides = { ...contract.task_overrides };
  if (key) task_overrides[task] = key;
  else delete task_overrides[task];
  return { ...contract, task_overrides };
}

/** Switching to "selected" starts from what is allowed now, so nothing changes until a box is cleared. */
export function setMode(contract: Contract, models: ModelRow[], mode: Contract["mode"]): Contract {
  if (mode === contract.mode) return contract;
  if (mode === "selected") return { ...contract, mode, selected: models.filter((row) => row.cleared).map((row) => row.key) };
  return { ...contract, mode, selected: [] };
}

/** The models the default can be: allowed chat models. */
export function defaultChoices(contract: Contract, models: ModelRow[]): ModelRow[] {
  return models.filter((row) => row.usedIn.includes("chat") && isAllowed(contract, row));
}

export function contractProblems(contract: Contract, models: ModelRow[]): string[] {
  const problems: string[] = [];
  if (contract.mode === "selected" && !models.some((row) => row.usedIn.includes("chat") && contract.selected.includes(row.key))) {
    problems.push("Pick at least one model for chat & agents.");
  }
  if (contract.default && !defaultChoices(contract, models).some((row) => row.key === contract.default)) {
    problems.push("The default model must be one of the allowed chat models.");
  }
  return problems;
}

/** The seat values on the Models page are read-only: the seat card in Agents › Seats & data classification is
 * their one editor, and the Models route refuses `seat_mode` (422 `seat_setting_via_seat_route`). */
export const companyModelsInSeatText = (on: boolean) => (on ? "On" : "Off");
export const seatModeText = (mode: Seat["mode"]) => (mode === "allowed" ? "Allowed" : "Off");

/** The body the Models page saves: the contract without any seat key. */
export function modelsSaveBody(contract: Contract): Omit<Contract, "seat"> {
  const { seat: _seat, ...rest } = contract;
  return rest;
}
export const SEAT_CARD_LINK_TEXT = "Changed in Agents › Seats & data classification";

export type SeatCheck = { state: "ok" | "bad" | "info"; text: string };

export function seatChecks(view: WorkspaceModels, contract: Contract, levelLabel: string): SeatCheck[] {
  const companyAllowed = view.models.some((row) => row.gateway && isAllowed(contract, row));
  return [
    view.seatAllowedAtLevel ? { state: "ok", text: `Claude Code seats are allowed at ${levelLabel}` }
      : { state: "bad", text: `Claude Code seats are off at ${levelLabel} (Classification)` },
    companyAllowed ? { state: "ok", text: "At least one company-gateway model is allowed" }
      : { state: "bad", text: "No company-gateway model is allowed" },
    { state: "info", text: "Usage is billed to this Workspace's budget (Rules → Budget)" },
  ];
}

const CODE_TEXT: Record<string, string> = {
  workspace_model_not_cleared: "a model is not cleared for this Workspace's level",
  workspace_models_empty: "pick at least one model for chat & agents",
  workspace_model_default_not_allowed: "the default must be an allowed chat model",
  workspace_seat_invalid: "the seat settings are not valid",
  seat_setting_via_seat_route: "seat settings are changed in Agents › Seats & data classification",
  workspace_model_unknown: "a model is no longer in the catalog",
  platform_admin_required: "only a platform admin can widen what this Workspace may use",
};

export function saveErrorText(error: unknown): string {
  const record = isRecord(error) ? error : {};
  const detail = isRecord(record.detail) ? record.detail : {};
  const code = text(record.code);
  const reason = text(detail.reason);
  return `Not saved: ${CODE_TEXT[code] ?? "the request was refused"}${reason ? ` (${reason})` : ""}.`;
}
