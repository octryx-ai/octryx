// The Setup guide: seven steps in the order a first installation needs them. The
// server says per step done / open / attention (GET /api/v1/admin/setup/onboarding); the person may skip the
// recommended steps (SSO, Roles) for now — a skipped step is not open, stays visible and can be resumed. Text per
// step comes from help/setup/<step>.md. Pure functions only.

export const SETUP_STEP_KEYS = ["workspace", "connectors", "sources", "models", "sso", "roles", "agents"] as const;
export type SetupStepKey = (typeof SETUP_STEP_KEYS)[number];
export type SetupStepStatus = "done" | "open" | "attention" | "skipped" | "unknown";

export type SetupStep = {
  key: SetupStepKey;
  scope: "platform" | "workspace";
  status: SetupStepStatus;
  reason: string;
  recommended: boolean;
  // The admin page that fixes the step when it is not the step's usual one (e.g. Default & fallback).
  target: string | null;
};

export type SetupStatus = {
  workspace: { id: string; name: string } | null;
  steps: SetupStep[];
};

const PLATFORM: ReadonlySet<SetupStepKey> = new Set(["workspace", "models", "sso"]);
const RECOMMENDED: ReadonlySet<SetupStepKey> = new Set(["sso", "roles"]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

/** The steps without a server answer (members, or before it loads): every step, status unknown. */
export function unknownSteps(): SetupStep[] {
  return SETUP_STEP_KEYS.map((key) => ({
    key, scope: PLATFORM.has(key) ? "platform" : "workspace", status: "unknown", reason: "", recommended: RECOMMENDED.has(key),
    target: null,
  }));
}

/** The server's answer, read strictly: unknown steps are dropped, missing ones stay unknown, order is fixed. */
export function readSetupStatus(payload: unknown): SetupStatus | null {
  if (!isRecord(payload) || !Array.isArray(payload.steps)) return null;
  const byKey = new Map<string, Record<string, unknown>>();
  for (const entry of payload.steps) if (isRecord(entry)) byKey.set(text(entry.key), entry);
  const steps = unknownSteps().map((step) => {
    const entry = byKey.get(step.key);
    const status = text(entry?.status);
    return entry && (status === "done" || status === "open" || status === "attention")
      ? {
        ...step, status, reason: text(entry.reason), target: text(entry.target) || null,
        // The server names the level when the deciding fact lives elsewhere (a shared connection is a platform fact).
        scope: text(entry.scope) === "platform" || text(entry.scope) === "workspace" ? text(entry.scope) : step.scope,
      } as SetupStep
      : step;
  });
  const workspace = isRecord(payload.workspace) && text(payload.workspace.id)
    ? { id: text(payload.workspace.id), name: text(payload.workspace.name) || text(payload.workspace.id) }
    : null;
  return { workspace, steps };
}

/** Skipped recommended steps that are not done count as skipped; a required step can never be skipped. */
export function applySkips(steps: SetupStep[], skipped: ReadonlySet<string>): SetupStep[] {
  return steps.map((step) =>
    step.recommended && skipped.has(step.key) && step.status !== "done" ? { ...step, status: "skipped" } : step);
}

export type SetupSummary = { done: number; total: number; requiredOpen: number };

export function setupSummary(steps: SetupStep[]): SetupSummary {
  return {
    done: steps.filter((step) => step.status === "done").length,
    total: steps.length,
    requiredOpen: steps.filter((step) => !step.recommended && (step.status === "open" || step.status === "attention")).length,
  };
}

/** "Setup: 3 of 7 done" while a required step is open; null once only done, skipped or recommended ones remain. */
export function setupProgressText(summary: SetupSummary | null): string | null {
  if (!summary || summary.requiredOpen === 0) return null;
  return `Setup: ${summary.done} of ${summary.total} done`;
}

// Skips are a person's own choice, kept in their browser (key versioned).
const SKIP_KEY = "octryx.setup.skipped.v1";
type Store = Pick<Storage, "getItem" | "setItem">;

export function readSkips(store: Store | null, userId: string | null | undefined): Set<string> {
  if (!store || !userId) return new Set();
  try {
    const parsed = JSON.parse(store.getItem(`${SKIP_KEY}.${userId}`) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((entry): entry is string => typeof entry === "string") : []);
  } catch {
    return new Set();
  }
}

export function writeSkips(store: Store | null, userId: string | null | undefined, skipped: ReadonlySet<string>) {
  if (!store || !userId) return;
  try {
    store.setItem(`${SKIP_KEY}.${userId}`, JSON.stringify([...skipped]));
  } catch {
    // Without storage the skip lasts for this page view.
  }
}

/** A step's button target: the help file's link, with the Workspace and the way back to the guide. */
export function stepHref(link: string, step: SetupStep, workspaceId: string | null): string {
  const url = new URL(step.target ? `/chat?area=admin&tab=${encodeURIComponent(step.target)}` : link, "https://placeholder.invalid");
  if (step.scope === "workspace" && workspaceId) url.searchParams.set("workspace_id", workspaceId);
  url.searchParams.set("from", "setup");
  return `${url.pathname}?${url.searchParams.toString()}`;
}

export const SETUP_GUIDE_HREF = "/chat?area=help&tab=setup";
