export type PointCondition = { where: string; label: string; action: string; reason: string };
export type PointAction = {
  surface: string; label: string; configuredAction: string; action: string; reason: string | null;
  conditions: PointCondition[];
};
export type PathDefault = { surface: string; label: string; action: string };
export type HandlingKind = {
  kind: string; label: string; action: string; defaultAction: string; isDefault: boolean;
  defaultActions: PathDefault[];
  surfaceDefaults: PointAction[];
  surfaceChoices: Record<string, PointAction[]>;
};
export type FixedRule = { rule: string; action: string; label: string };
export type FixedPoint = { surface: string; label: string; rules: FixedRule[] };
export type GovernedAlias = { alias: string; label: string };
export type ContentHandling = {
  workspaceId: string; canEdit: boolean; actions: string[];
  governanceAlias: string | null;
  governanceAliases: GovernedAlias[];
  kinds: HandlingKind[]; fixed: FixedPoint[];
};
export type HandlingChoice = string;

export const DEFAULT_CHOICE = "default";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const list = (value: unknown) => (Array.isArray(value) ? value : []);

const ACTION_TEXT: Record<string, string> = {
  refuse: "Refuse",
  mask: "Mask",
  reroute: "Reroute",
  mask_reroute: "Mask and reroute",
  report: "Allow (recorded)",
  none: "Not acted on",
  review: "Send for review",
  deny: "Deny",
  withhold: "Withhold",
};
export const actionText = (action: string) => ACTION_TEXT[action] || action;

export const ACTION_EXPLANATIONS: { action: string; text: string }[] = [
  { action: "report", text: "Allow (recorded): the text goes to the model unchanged; the finding is recorded." },
  { action: "mask", text: "Mask: the values are replaced with placeholders before the model sees them." },
  { action: "refuse", text: "Refuse: the request is stopped." },
  { action: "reroute", text: "Reroute: the request is sent to the Workspace's governance alias instead." },
  { action: "mask_reroute", text: "Mask and reroute: the values are masked and the request goes to the Workspace's governance alias." },
];

export const reroutes = (action: string) => action === "reroute" || action === "mask_reroute";

function readPoints(value: unknown): PointAction[] {
  return list(value).filter(isRecord)
    .map((item) => ({
      surface: text(item.surface), label: text(item.label) || text(item.surface),
      configuredAction: text(item.configured_action), action: text(item.action), reason: text(item.reason) || null,
      conditions: list(item.conditions).filter(isRecord)
        .map((rule) => ({ where: text(rule.where), label: text(rule.label) || text(rule.where), action: text(rule.action), reason: text(rule.reason) }))
        .filter((rule) => rule.where && rule.action),
    }))
    .filter((item) => item.surface && item.action);
}

function readChoices(value: unknown): Record<string, PointAction[]> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([choice, points]) => [choice, readPoints(points)]));
}

export function readHandlingKind(value: unknown): HandlingKind | null {
  if (!isRecord(value) || !text(value.kind)) return null;
  const kind = text(value.kind);
  return {
    kind, label: text(value.label) || kind, action: text(value.action), defaultAction: text(value.default_action),
    isDefault: value.is_default === true,
    defaultActions: list(value.default_actions).filter(isRecord)
      .map((item) => ({ surface: text(item.surface), label: text(item.label) || text(item.surface), action: text(item.action) }))
      .filter((item) => item.surface && item.action),
    surfaceDefaults: readPoints(value.surface_defaults),
    surfaceChoices: readChoices(value.surface_choices),
  };
}

export function readContentHandling(payload: unknown): ContentHandling | null {
  if (!isRecord(payload) || !Array.isArray(payload.kinds)) return null;
  // `none` is never choosable, whatever the server lists.
  const actions = list(payload.actions).map(text).filter((action) => action && action !== "none" && action !== DEFAULT_CHOICE);
  return {
    workspaceId: text(payload.workspace_id),
    canEdit: payload.can_edit === true,
    actions,
    governanceAlias: text(payload.governance_alias) || null,
    governanceAliases: list(payload.governance_aliases).filter(isRecord)
      .map((item) => ({ alias: text(item.alias), label: text(item.label) || text(item.alias) })).filter((item) => item.alias),
    kinds: payload.kinds.map(readHandlingKind).filter((kind): kind is HandlingKind => kind !== null),
    fixed: list(payload.fixed).filter(isRecord).map(readFixedPoint).filter((point) => point.surface && point.rules.length),
  };
}

function readFixedPoint(value: Record<string, unknown>): FixedPoint {
  return {
    surface: text(value.surface),
    label: text(value.label) || text(value.surface),
    rules: list(value.rules).filter(isRecord)
      .map((item) => ({ rule: text(item.rule), action: text(item.action), label: text(item.label) || text(item.rule) }))
      .filter((item) => item.rule),
  };
}

export const initialChoice = (kind: HandlingKind): HandlingChoice => (kind.isDefault ? DEFAULT_CHOICE : kind.action);

export const choiceUnchanged = (choice: HandlingChoice, kind: HandlingKind) => choice === initialChoice(kind);

export const NO_ALIASES_TEXT = "A governed alias must exist before content can be rerouted; ask a platform admin to set one up.";
export const ALIAS_REQUIRED_TEXT = "Rerouting sends the content to the Workspace's governance alias: set it above first.";

export function choiceProblem(choice: HandlingChoice, data: Pick<ContentHandling, "actions" | "governanceAlias">): string | null {
  if (choice !== DEFAULT_CHOICE && !data.actions.includes(choice)) return "Choose an action.";
  if (reroutes(choice) && !data.governanceAlias) return ALIAS_REQUIRED_TEXT;
  return null;
}

export const choiceBody = (choice: HandlingChoice) => ({ action: choice });

export const reroutingKinds = (data: Pick<ContentHandling, "kinds">) =>
  data.kinds.filter((kind) => !kind.isDefault && reroutes(kind.action));

export function aliasProblem(alias: string | null, data: Pick<ContentHandling, "governanceAliases" | "kinds">): string | null {
  if (alias === null) {
    const kinds = reroutingKinds(data);
    return kinds.length ? `These kinds still reroute to it: ${kinds.map((kind) => kind.label).join(", ")}. Set them to another action first.` : null;
  }
  if (!data.governanceAliases.some((item) => item.alias === alias)) return "Choose a governed alias from the list.";
  return null;
}

export const aliasBody = (alias: string | null) => ({ alias });

export const aliasText = (alias: string | null) => alias ?? "None set: no kind can be rerouted.";

export const PLATFORM_ONLY_TEXT = "Not acted on at every place: some places check only some kinds.";

const REASON_LINES: [string, (labels: string) => string][] = [
  ["platform_calls_only", (labels) => `${PLATFORM_ONLY_TEXT} There: ${labels}.`],
  ["deferred_to_model_entrance", (labels) =>
    `At these places the content goes on unchanged; the action applies where it next reaches a model: ${labels}.`],
  ["command_review", (labels) => `Here the command is sent for review instead (a command cannot be masked): ${labels}.`],
  ["command_denied", (labels) => `Here the command is denied: ${labels}.`],
  ["content_route_unavailable", (labels) => `At these places this request is refused with content_route_unavailable instead: ${labels}.`],
  ["reroute_masked", (labels) => `At these places the value is masked instead of rerouted: ${labels}.`],
];

export function pointLines(points: PointAction[], action: string): string[] {
  const differing = points.filter((point) => point.action !== action);
  const lines: string[] = [];
  for (const [reason, line] of REASON_LINES) {
    const labels = differing.filter((point) => point.reason === reason)
      .map((point) => (reason === "platform_calls_only" ? `${point.label}: ${actionText(point.action)}` : point.label));
    if (labels.length) lines.push(line(labels.join("; ")));
  }
  const known = new Set(REASON_LINES.map(([reason]) => reason));
  const other = differing.filter((point) => !point.reason || !known.has(point.reason));
  if (other.length) lines.push(`Elsewhere: ${other.map((point) => `${point.label}: ${actionText(point.action)}`).join("; ")}.`);
  for (const point of points) {
    for (const rule of point.conditions) lines.push(`${rule.label}: ${actionText(rule.action)} instead (${point.label}).`);
  }
  return lines;
}

export const surfaceDefaultLines = (kind: HandlingKind) => pointLines(kind.surfaceDefaults, kind.action);

export function choicePreviewLines(choice: HandlingChoice, kind: HandlingKind): string[] {
  const chosen = choice === DEFAULT_CHOICE ? kind.defaultAction : choice;
  return pointLines(kind.surfaceChoices[choice] ?? [], chosen);
}

// The shipped default per path when the paths differ (email: masked on platform calls, recorded on gateway routes).
export function shippedDefaultText(kind: HandlingKind): string {
  const actions = new Set(kind.defaultActions.map((item) => item.action));
  if (actions.size < 2) return actionText(kind.defaultActions[0]?.action ?? kind.defaultAction);
  return kind.defaultActions.map((item) => `${item.label}: ${actionText(item.action)}`).join("; ");
}

export const defaultOptionText = (kind: HandlingKind) => `Use default (${shippedDefaultText(kind)})`;

export function effectiveText(kind: HandlingKind, governanceAlias: string | null): string {
  const words = actionText(kind.action);
  return reroutes(kind.action) && governanceAlias ? `${words} to ${governanceAlias}` : words;
}

export const READ_ONLY_TEXT = "Only Workspace admins and owners (or platform admins) can change how sensitive content is handled here.";
export const NOT_FOUND_TEXT = "This Workspace does not exist, or you are not a member of it.";

const REFUSAL_TEXT: Record<string, string> = {
  content_handling_kind_unknown: "This content kind cannot be configured.",
  content_handling_action_invalid: "This action cannot be chosen for this content kind.",
  content_handling_alias_required: ALIAS_REQUIRED_TEXT,
  content_handling_alias_unknown: "The chosen alias is not a governed alias (any more); choose another one.",
};
export const ALIAS_IN_USE_TEXT = "Kinds still reroute to the governance alias; set them to another action before clearing it.";
export const CONFLICT_TEXT = "Someone else changed this setting at the same time, so yours was not saved. Reload the page and apply your change again.";

type RequestError = { status?: unknown; code?: unknown; message?: unknown };
const errorRecord = (error: unknown): RequestError => (isRecord(error) ? error : {});

export function contentHandlingSaveErrorText(error: unknown): string {
  const record = errorRecord(error);
  if (record.status === 422 && typeof record.code === "string" && REFUSAL_TEXT[record.code]) return REFUSAL_TEXT[record.code];
  if (record.status === 409 && record.code === "content_handling_conflict") return CONFLICT_TEXT;
  if (record.status === 409 && record.code === "content_handling_alias_in_use") return ALIAS_IN_USE_TEXT;
  if (record.status === 403) return "Only Workspace admins and owners can change this.";
  if (record.status === 404) return NOT_FOUND_TEXT;
  const message = typeof record.message === "string" && record.message ? record.message : "the request failed";
  return `The setting could not be saved: ${message}.`;
}

export function contentHandlingLoadErrorText(error: unknown): string {
  const record = errorRecord(error);
  if (record.status === 404) return NOT_FOUND_TEXT;
  const message = typeof record.message === "string" && record.message ? record.message : "the request failed";
  return `The sensitive content handling could not be loaded: ${message}.`;
}
