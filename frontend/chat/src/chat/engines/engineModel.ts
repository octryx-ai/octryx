const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const textList = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);

export const CLAUDE_CODE = "claude_code";
export const CODEX = "codex";
export const ENGINES: readonly string[] = [CLAUDE_CODE, CODEX];

const NAMES: Record<string, string> = { [CLAUDE_CODE]: "Claude Code", [CODEX]: "Codex" };

/** A job without an engine runs on Claude Code; an unknown id is never shown raw. */
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

export function effectiveLine(effective: EffectiveEngine): string {
  return `You use: ${engineLabel(effective.engine)} (${sourceText(effective.source)})`;
}

export function notAllowedNotice(effective: EffectiveEngine): string | null {
  if (!effective.personChoice || effective.source === "person") return null;
  return `Your choice ${engineLabel(effective.personChoice)} is not allowed in this Workspace; the Workspace default applies.`;
}

export type EngineOption = { value: string; label: string; disabled: boolean; hint?: string };

export const NOT_ALLOWED_HINT = "Not allowed in this Workspace";

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

export function personalOptions(effective: EffectiveEngine, engines: readonly string[] = ENGINES): EngineOption[] {
  return [
    { value: "", label: `Workspace default (${engineLabel(effective.workspaceDefault)})`, disabled: false },
    ...engines.map((engine) => {
      const allowed = effective.allowed.includes(engine);
      return { value: engine, label: engineLabel(engine), disabled: !allowed, ...(allowed ? {} : { hint: NOT_ALLOWED_HINT }) };
    }),
  ];
}

export function personalValue(effective: EffectiveEngine): string {
  return effective.source === "person" && effective.personChoice ? effective.personChoice : "";
}

export type WorkspaceDraft = { allowed: string[]; default: string };

export function workspaceDraftOf(answer: WorkspaceEngines): WorkspaceDraft {
  return { allowed: [...answer.allowed], default: answer.default ?? "" };
}

export function toggleAllowed(draft: WorkspaceDraft, engine: string, on: boolean, engines: readonly string[] = ENGINES): WorkspaceDraft {
  const allowed = engines.filter((item) => (item === engine ? on : draft.allowed.includes(item)));
  return { allowed, default: draft.default && !allowed.includes(draft.default) ? "" : draft.default };
}

export function allowedProblem(allowed: string[]): string | null {
  return allowed.length ? null : "Allow at least one engine.";
}

export function sameDraft(a: WorkspaceDraft, b: WorkspaceDraft): boolean {
  return a.default === b.default && a.allowed.join(",") === b.allowed.join(",");
}

export function workspaceEnginesBody(draft: WorkspaceDraft): { allowed: string[]; default: string | null } {
  return { allowed: [...draft.allowed], default: draft.default || null };
}

export function personalEngineBody(value: string): { engine: string | null } {
  return { engine: value || null };
}

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
