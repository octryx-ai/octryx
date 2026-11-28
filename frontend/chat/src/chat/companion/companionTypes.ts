// Octryx companion: the shapes of the attention payload, its runs and the octopus' face and arms.

export type AttentionKind =
  | "question" | "gate" | "device_approval" | "done" | "problem" | "budget" | "allowance" | "handover"
  // A running Claude Code session wrote back (live), a turn on the person's Mac ended (turn).
  | "live" | "turn"
  // A session in the Workspace pool that the person can run now.
  | "pool";
export type AttentionSeverity = "action" | "warning" | "info";
export type ActionTone = "primary" | "neutral" | "danger";
export type AttentionInput = { kind: "text"; label: string; placeholder: string; required: boolean; field: string };
export type AttentionRequest = { method: "POST" | "PUT" | "PATCH" | "DELETE"; path: string; body: Record<string, unknown> };
export type AttentionAction = { key: string; label: string; tone: ActionTone; input: AttentionInput | null; request: AttentionRequest };
export type AttentionItem = {
  key: string;
  kind: AttentionKind;
  id: string;
  title: string;
  subtitle: string;
  createdAt: string | null;
  expiresAt: string | null;
  severity: AttentionSeverity;
  workspace: { id: string; name: string } | null;
  workItem: { id: string; key: string; title: string } | null;
  sessionId: string | null;
  // The workflow run the item is about (`run.id`; a run, done or handover item's own id), so a run is shown once.
  runId: string | null;
  text: string;
  link: { href: string; label: string } | null;
  actions: AttentionAction[];
  percent: number | null;
  // A Mac turn of an imported sample run (backend attention/device_items): it never ran on this person's Mac.
  sample?: boolean;
};
export type RunState = "working" | "needs_you" | "done" | "problem";
export type RunningAgent = {
  key: string;
  label: string;
  state: RunState;
  currentNode: string;
  target: RuntimeTarget | null;
  workItem: { id: string; key: string; title: string } | null;
  sessionId: string | null;
  updatedAt: string | null;
  // The server's run status ("running", "waiting", …) and wait reason, when sent.
  status: string;
  waitingKind: string;
  pauseReason: string;
};
export type RuntimeTarget = {
  kind: string; label: string; deviceName: string; folder: string; profile: string; online: boolean | null; resolvedFrom: string; reason: string;
};
export type Attention = {
  items: AttentionItem[];
  running: RunningAgent[];
  count: number;
  cursor: string | null;
  quiet: { active: boolean; until: string | null };
};
export type FaceState = "calm" | "open" | "worry" | "sleep";
export type NodeState = "run" | "wait" | "done" | "fail" | "idle" | "off";
export type ArmNode = { state: NodeState; label: string; more: number };
export type AttentionGroups = { needs: AttentionItem[]; problems: AttentionItem[]; running: RunningAgent[]; done: AttentionItem[] };
export type QuietHours = { enabled: boolean; start: string; end: string; timezone: string };

export const DEFAULT_QUIET_HOURS: QuietHours = { enabled: true, start: "19:00", end: "08:00", timezone: "Europe/Zurich" };
export const ARM_COUNT = 8;
