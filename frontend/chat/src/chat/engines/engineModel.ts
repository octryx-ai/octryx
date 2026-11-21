// Coding engine: Claude Code or Codex. Pure: no requests, no React.
//
// Contract (backend):
//   GET|PUT /api/v1/admin/agent-engine -> {default, engines, can_edit}; PUT {default} (platform admins).
//   GET|PUT /api/v1/workspaces/{id}/agent-gateway/engines
//     -> {project_id, engines, workspace: {allowed, default|null}, source: 'default'|'workspace',
//         effective: {engine, source: 'person'|'workspace'|'platform', allowed, workspace_default, platform_default,
//                     person_choice|null}, can_edit}
//     PUT {allowed, default?}; a missing/null default means "platform default".
//   PUT …/engines/me {engine|null} -> the same shape; null uses the Workspace default.
//   422 {detail: {errors: [{code, field}]}}.
// Device jobs carry `engine` ('claude_code' | 'codex' | null); null (not yet offered) means Claude Code.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const textList = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);

export const CLAUDE_CODE = "claude_code";
export const CODEX = "codex";
/** The server's order; also the order of checkboxes and options. */
export const ENGINES: readonly string[] = [CLAUDE_CODE, CODEX];

const NAMES: Record<string, string> = { [CLAUDE_CODE]: "Claude Code", [CODEX]: "Codex" };

/** The engine in words. A job without one runs on Claude Code; an unknown id is never shown raw. */
export function engineLabel(engine: string | null | undefined): string {
  const id = String(engine ?? "").trim();
  if (!id) return NAMES[CLAUDE_CODE];
  if (NAMES[id]) return NAMES[id];
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export type EngineSource = "person" | "workspace" | "platform";

const SOURCE_TEXT: Record<EngineSource, string> = {
  person: "your choice",
  workspace: "Workspace default",
  platform: "platform default",
};

export function sourceText(source: EngineSource): string {
  return SOURCE_TEXT[source];
}

// ---- Answers ------------------------------------------------------------------------------------------------------

export type PlatformEngine = { default: string; engines: string[]; canEdit: boolean };

export function readPlatformEngine(payload: unknown): PlatformEngine | null {
  if (!isRecord(payload) || !text(payload.default)) return null;
  const engines = textList(payload.engines);
  return { default: text(payload.default), engines: engines.length ? engines : [...ENGINES], canEdit: payload.can_edit === true };
}

export type EffectiveEngine = {
  engine: string;
  source: EngineSource;
  allowed: string[];
  workspaceDefault: string;
  platformDefault: string;
  personChoice: string | null;
};

export type WorkspaceEngines = {
  projectId: string;
  engines: string[];
  allowed: string[];
  /** null: the platform default applies. */
  default: string | null;
  source: "default" | "workspace";
  effective: EffectiveEngine;
  canEdit: boolean;
};

function readEffective(raw: unknown): EffectiveEngine | null {
  if (!isRecord(raw) || !text(raw.engine)) return null;
  const source = raw.source === "person" || raw.source === "workspace" ? raw.source : "platform";
  return {
    engine: text(raw.engine),
    source,
    allowed: textList(raw.allowed),
    workspaceDefault: text(raw.workspace_default) || text(raw.engine),
    platformDefault: text(raw.platform_default) || CLAUDE_CODE,
    personChoice: text(raw.person_choice) || null,
  };
}

/** The Workspace's engines as the server sent them; null when the answer is not one (nothing is guessed). */
export function readWorkspaceEngines(payload: unknown): WorkspaceEngines | null {
  if (!isRecord(payload) || !isRecord(payload.workspace)) return null;
  const effective = readEffective(payload.effective);
  const allowed = textList(payload.workspace.allowed);
  if (!effective || !allowed.length) return null;
  const engines = textList(payload.engines);
  return {
    projectId: text(payload.project_id),
    engines: engines.length ? engines : [...ENGINES],
    allowed,
    default: text(payload.workspace.default) || null,
    source: payload.source === "workspace" ? "workspace" : "default",
    effective,
    canEdit: payload.can_edit === true,
  };
}

// ---- What applies to you ------------------------------------------------------------------------------------------

/** "You use: Codex (your choice)". */
export function effectiveLine(effective: EffectiveEngine): string {
  return `You use: ${engineLabel(effective.engine)} (${sourceText(effective.source)})`;
}

/** The person's stored choice is not allowed in this Workspace, so the Workspace default applies instead. */
export function notAllowedNotice(effective: EffectiveEngine): string | null {
  if (!effective.personChoice || effective.source === "person") return null;
  return `Your choice ${engineLabel(effective.personChoice)} is not allowed in this Workspace; the Workspace default applies.`;
}

// ---- Options ------------------------------------------------------------------------------------------------------

export type EngineOption = { value: string; label: string; disabled: boolean; hint?: string };

export const NOT_ALLOWED_HINT = "Not allowed in this Workspace";

/** The Workspace default select: "Platform default (<engine>)" (value "") and the engines the draft allows. */
export function workspaceDefaultOptions(allowed: string[], platformDefault: string, engines: readonly string[] = ENGINES): EngineOption[] {
  return [
    { value: "", label: `Platform default (${engineLabel(platformDefault)})`, disabled: false },
    ...engines.filter((engine) => allowed.includes(engine)).map((engine) => ({ value: engine, label: engineLabel(engine), disabled: false })),
  ];
}

/** When the platform default is not allowed here, the server uses the first allowed engine instead; null otherwise. */
export function platformDefaultHint(allowed: string[], platformDefault: string, engines: readonly string[] = ENGINES): string | null {
  if (!allowed.length || allowed.includes(platformDefault)) return null;
  const first = engines.find((engine) => allowed.includes(engine)) ?? allowed[0];
  return `${engineLabel(platformDefault)} is not allowed here, so "Platform default" means ${engineLabel(first)}.`;
}

/** A person's choice: "Workspace default (<engine>)" (value "") and every engine, the not-allowed ones disabled. */
export function personalOptions(effective: EffectiveEngine, engines: readonly string[] = ENGINES): EngineOption[] {
  return [
    { value: "", label: `Workspace default (${engineLabel(effective.workspaceDefault)})`, disabled: false },
    ...engines.map((engine) => {
      const allowed = effective.allowed.includes(engine);
      return { value: engine, label: engineLabel(engine), disabled: !allowed, ...(allowed ? {} : { hint: NOT_ALLOWED_HINT }) };
    }),
  ];
}

/** The select's value for the person: their choice while it counts here, else the Workspace default (""). */
export function personalValue(effective: EffectiveEngine): string {
  return effective.source === "person" && effective.personChoice ? effective.personChoice : "";
}

// ---- Drafts and bodies --------------------------------------------------------------------------------------------

export type WorkspaceDraft = { allowed: string[]; default: string };

export function workspaceDraftOf(answer: WorkspaceEngines): WorkspaceDraft {
  return { allowed: [...answer.allowed], default: answer.default ?? "" };
}

/** Checking or clearing one engine; keeps the server's order and drops a default that is no longer allowed. */
export function toggleAllowed(draft: WorkspaceDraft, engine: string, on: boolean, engines: readonly string[] = ENGINES): WorkspaceDraft {
  const allowed = engines.filter((item) => (item === engine ? on : draft.allowed.includes(item)));
  return { allowed, default: draft.default && !allowed.includes(draft.default) ? "" : draft.default };
}

/** The same rule as the server, said at the field; null when the draft is valid. */
export function allowedProblem(allowed: string[]): string | null {
  return allowed.length ? null : "Allow at least one engine.";
}

export function sameDraft(a: WorkspaceDraft, b: WorkspaceDraft): boolean {
  return a.default === b.default && a.allowed.join(",") === b.allowed.join(",");
}

/** PUT …/engines: "Platform default" sends `default: null`. */
export function workspaceEnginesBody(draft: WorkspaceDraft): { allowed: string[]; default: string | null } {
  return { allowed: [...draft.allowed], default: draft.default || null };
}

/** PUT …/engines/me: "Workspace default" sends `engine: null`. */
export function personalEngineBody(value: string): { engine: string | null } {
  return { engine: value || null };
}

// ---- Refusals -----------------------------------------------------------------------------------------------------

export type EngineErrors = { allowed?: string; default?: string; engine?: string; general?: string };

const CODE_TEXT: Record<string, string> = {
  allowed_must_name_an_engine: "Allow at least one engine.",
  duplicate_engine: "Each engine can be allowed only once.",
  engine_unknown: "Choose Claude Code or Codex.",
  default_not_allowed: "The default must be one of the allowed engines.",
  agent_gateway_policy_invalid: "The Workspace's coding-tool policy has an invalid value; fix it under Coding tools & devices first.",
  engine_not_allowed_in_workspace: "This engine is not allowed in this Workspace.",
};

const FORBIDDEN = {
  platform: "only platform admins can change the platform default.",
  workspace: "only Workspace admins and owners can change this.",
  person: "you are not allowed to change this setting.",
} as const;

/** A refused save in words, placed at its field (`agent_gateway_policy.engines.allowed[1]` → allowed). */
export function engineSaveErrors(status: number, body: unknown, scope: "platform" | "workspace" | "person" = "workspace"): EngineErrors {
  const detail = isRecord(body) ? body.detail : null;
  if (status === 422 && isRecord(detail) && Array.isArray(detail.errors)) {
    const errors: EngineErrors = {};
    for (const error of detail.errors.filter(isRecord)) {
      const code = text(error.code);
      const words = CODE_TEXT[code] ?? "This value was refused.";
      const field = text(error.field).split(".").pop()?.replace(/\[\d+\]$/, "");
      if (code !== "agent_gateway_policy_invalid" && (field === "allowed" || field === "default" || field === "engine")) {
        errors[field] = words;
      } else errors.general = `Not saved: ${words}`;
    }
    if (Object.keys(errors).length) return errors;
  }
  if (status === 403) return { general: `Not saved: ${FORBIDDEN[scope]}` };
  if (status === 404) return { general: "Not saved: this Workspace was not found, or you are not a member." };
  return { general: "Not saved: the request failed." };
}
