// Octryx companion: reading the attention payload (GET /api/v1/attention).
import { runName } from "./companionLabels";
import { NEEDS_YOU, needsYou } from "./companionGroups";
import type {
  Attention, AttentionAction, AttentionInput, AttentionItem, AttentionKind, AttentionRequest, RunState, RunningAgent, RuntimeTarget,
} from "./companionTypes";
import { optStr, pick, record, str } from "./companionValues";

// "handover": a session (or run) handed over to the person (accept/decline); "pool": one the person can take over.
const KINDS: AttentionKind[] = ["question", "gate", "device_approval", "done", "problem", "budget", "allowance", "handover", "live", "turn",
  "pool"];
const RUN_STATES: RunState[] = ["working", "needs_you", "done", "problem"];
const METHODS: AttentionRequest["method"][] = ["POST", "PUT", "PATCH", "DELETE"];

function readRef(value: unknown): { id: string; key: string; title: string } | null {
  const ref = record(value);
  if (!ref || !str(ref.id)) return null;
  return { id: str(ref.id), key: str(ref.key), title: str(ref.title) };
}

/** Only same-origin API paths are ever sent; anything else drops the action. */
function readRequest(value: unknown): AttentionRequest | null {
  const request = record(value);
  const path = str(request?.path);
  if (!request || !path.startsWith("/api/") || path.includes("//") || path.includes("..")) return null;
  const method = str(request.method).toUpperCase() || "POST";
  if (!METHODS.includes(method as AttentionRequest["method"])) return null;
  return { method: method as AttentionRequest["method"], path, body: { ...(record(request.body) ?? {}) } };
}

function readInput(value: unknown): AttentionInput | null {
  const input = record(value);
  if (!input || !str(input.field)) return null;
  return { kind: "text", label: str(input.label), placeholder: str(input.placeholder),
    required: input.required === true, field: str(input.field) };
}

export function readAttentionAction(value: unknown): AttentionAction | null {
  const action = record(value);
  const request = readRequest(action?.request);
  if (!action || !str(action.key) || !str(action.label) || !request) return null;
  return { key: str(action.key), label: str(action.label), tone: pick(action.tone, ["primary", "neutral", "danger"] as const, "neutral"),
    input: readInput(action.input), request };
}

export function readAttentionItem(value: unknown): AttentionItem | null {
  const item = record(value);
  if (!item || !KINDS.includes(item.kind as AttentionKind) || !str(item.id)) return null;
  const kind = item.kind as AttentionKind;
  const workspace = record(item.workspace);
  const link = record(item.link);
  const href = str(link?.href);
  const actions = (Array.isArray(item.actions) ? item.actions : []).map(readAttentionAction).filter((a): a is AttentionAction => a !== null);
  const key = str(item.key) || `${kind}:${str(item.id)}`;
  // A done item without its own "dismiss" action still gets one: POST /api/v1/attention/dismiss {key}.
  if (kind === "done" && !actions.some((action) => action.key === "dismiss")) {
    actions.push({ key: "dismiss", label: "Dismiss", tone: "neutral", input: null, request: { method: "POST", path: "/api/v1/attention/dismiss", body: { key } } });
  }
  const percent = typeof item.percent === "number" && Number.isFinite(item.percent) ? item.percent : null;
  // An activity problem about a run (looping, silent, jobs refused) is the run's own entry.
  const problemRun = kind === "problem" && str(record(record(item.problem)?.object)?.type) === "workflow_run";
  // A handover's id is its session when no run moves with it: only its run reference names a run.
  const runId = str(record(item.run)?.id) || (/^(run|done):/.test(key) || problemRun ? str(item.id) : "");
  return {
    key, kind, id: str(item.id), title: str(item.title) || kind.replace("_", " "),
    subtitle: str(item.subtitle), createdAt: optStr(item.created_at), expiresAt: optStr(item.expires_at),
    severity: pick(item.severity, ["action", "warning", "info"] as const, NEEDS_YOU.includes(kind) ? "action" : "info"),
    workspace: workspace && str(workspace.id) ? { id: str(workspace.id), name: str(workspace.name) || str(workspace.id) } : null,
    workItem: readRef(item.work_item), sessionId: optStr(item.session_id), runId: runId || null, text: str(item.text),
    link: href.startsWith("/") && !href.startsWith("//") ? { href, label: str(link?.label) || "Open" } : null,
    actions,
    percent, sample: item.sample === true,
  };
}

export function readRunningAgent(value: unknown): RunningAgent | null {
  const run = record(value);
  if (!run) return null;
  const key = str(run.id) || str(run.run_id) || str(run.session_id);
  if (!key) return null;
  const target = record(run.runtime_target);
  const workItem = readRef(run.work_item);
  const runTarget: RuntimeTarget | null = target ? {
    kind: str(target.kind), label: str(target.label), deviceName: str(target.device_name), folder: str(target.folder), profile: str(target.profile),
    online: typeof target.online === "boolean" ? target.online : null, resolvedFrom: str(target.resolved_from), reason: str(target.reason),
  } : null;
  return {
    key, state: pick(run.state, RUN_STATES, "working"), currentNode: str(run.current_node),
    // Ticket key first: " Add capitalize_words", else the run's own title.
    label: runName(workItem?.key || str(run.ticket_key), workItem?.title || str(run.title),
      str(run.title) || runTarget?.label || "Agent run"),
    target: runTarget, workItem, sessionId: optStr(run.session_id), updatedAt: optStr(run.updated_at),
    status: str(run.status), waitingKind: str(run.waiting_kind), pauseReason: str(run.pause_reason),
  };
}


/** GET /api/v1/attention; null when the answer is not an attention payload. */
export function readAttention(payload: unknown): Attention | null {
  const value = record(payload);
  if (!value || !Array.isArray(value.items)) return null;
  const items = value.items.map(readAttentionItem).filter((item): item is AttentionItem => item !== null);
  const running = (Array.isArray(value.running) ? value.running : []).map(readRunningAgent).filter((run): run is RunningAgent => run !== null);
  const quiet = record(value.quiet);
  return {
    items, running, count: typeof value.count === "number" ? value.count : needsYou(items).length,
    cursor: optStr(value.cursor), quiet: { active: quiet?.active === true, until: optStr(quiet?.until) },
  };
}
