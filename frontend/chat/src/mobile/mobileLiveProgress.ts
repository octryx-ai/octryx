import { liveText } from "./mobilePayloadValues";

export type ProgressEvent = {
  seq: number;
  kind: "text" | "tool" | "result" | "prompt" | "compact";
  at: string;
  text: string;
  tool: string;
  input: string;
  line: string;
  from: string;
  id: string;
  ok: boolean;
};

export type LiveProgress = { events: ProgressEvent[]; lastSeq: number; status: string; running: boolean; more: boolean };

const PROGRESS_KINDS = new Set(["text", "tool", "result", "prompt", "compact"]);

export function readLiveProgress(raw: unknown): LiveProgress {
  const page = (raw ?? {}) as Record<string, unknown>;
  const events = (Array.isArray(page.events) ? page.events : [])
    .map((entry) => (entry ?? {}) as Record<string, unknown>)
    .filter((entry) => typeof entry.seq === "number" && PROGRESS_KINDS.has(String(entry.kind)))
    .map((entry) => ({
      seq: entry.seq as number,
      kind: entry.kind as ProgressEvent["kind"],
      at: liveText(entry.at),
      text: liveText(entry.text),
      tool: liveText(entry.tool),
      input: liveText(entry.input),
      line: liveText(entry.line),
      from: liveText(entry.from),
      id: liveText(entry.id),
      ok: entry.ok !== false,
    }));
  return {
    events,
    lastSeq: typeof page.last_seq === "number" ? page.last_seq : events.at(-1)?.seq ?? 0,
    status: liveText(page.status),
    running: page.running === true,
    more: page.more === true,
  };
}

export function mergeProgress(known: ProgressEvent[], fresh: ProgressEvent[], keep = 400): ProgressEvent[] {
  const bySeq = new Map(known.map((event) => [event.seq, event]));
  for (const event of fresh) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-keep);
}

export type ProgressStep =
  | { key: string; kind: "text"; at: string; text: string }
  | { key: string; kind: "prompt"; at: string; text: string; from: string }
  | { key: string; kind: "compact"; at: string }
  | { key: string; kind: "tool"; at: string; tool: string; input: string; done: boolean; ok: boolean; line: string };

export function progressSteps(events: ProgressEvent[]): ProgressStep[] {
  const steps: ProgressStep[] = [];
  const open = new Map<string, number>();
  for (const event of events) {
    const key = `p-${event.seq}`;
    if (event.kind === "tool") {
      open.set(event.id, steps.length);
      steps.push({ key, kind: "tool", at: event.at, tool: event.tool, input: event.input, done: false, ok: true, line: "" });
    } else if (event.kind === "result") {
      const index = open.get(event.id);
      const step = index === undefined ? undefined : steps[index];
      if (step && step.kind === "tool") {
        steps[index as number] = { ...step, done: true, ok: event.ok, line: event.line };
        open.delete(event.id);
      }
    } else if (event.kind === "text") {
      steps.push({ key, kind: "text", at: event.at, text: event.text });
    } else if (event.kind === "prompt") {
      steps.push({ key, kind: "prompt", at: event.at, text: event.text, from: event.from });
    } else {
      steps.push({ key, kind: "compact", at: event.at });
    }
  }
  return steps;
}

export function liveStatusText(status: string, running: boolean): string {
  if (!running) return "Not reporting";
  return status === "busy" ? "Working…" : status === "waiting" ? "Waiting for input" : "Idle";
}

export type ToolStep = Extract<ProgressStep, { kind: "tool" }>;
export type ProgressBlock =
  | { kind: "step"; key: string; at: string; step: Exclude<ProgressStep, ToolStep> }
  | { kind: "tools"; key: string; at: string; tools: ToolStep[]; failed: number; running: boolean };

export function groupSteps(steps: ProgressStep[]): ProgressBlock[] {
  const blocks: ProgressBlock[] = [];
  for (const step of steps) {
    const last = blocks[blocks.length - 1];
    if (step.kind !== "tool") {
      blocks.push({ kind: "step", key: step.key, at: step.at, step });
    } else if (last && last.kind === "tools") {
      last.tools.push(step);
      last.failed += step.done && !step.ok ? 1 : 0;
      last.running = last.running || !step.done;
    } else {
      blocks.push({ kind: "tools", key: `g-${step.key}`, at: step.at, tools: [step],
        failed: step.done && !step.ok ? 1 : 0, running: !step.done });
    }
  }
  return blocks;
}

export function groupSummary(group: Extract<ProgressBlock, { kind: "tools" }>): string {
  const count = group.tools.length;
  if (group.failed) return `${group.failed} of ${count} failed`;
  const byTool = new Map<string, number>();
  for (const tool of group.tools) byTool.set(tool.tool, (byTool.get(tool.tool) ?? 0) + 1);
  const names = [...byTool.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([name, times]) => (times > 1 ? `${name} ×${times}` : name));
  return [`${count} ${count === 1 ? "step" : "steps"}`, ...names].join(" · ");
}

const FILE_TOOLS = new Set(["Read", "Edit", "Write", "MultiEdit", "NotebookEdit"]);

const baseName = (path: string) => path.replace(/\/+$/, "").split("/").pop() || path;
// An absolute or home path (``/Volumes/…/PLAN.md``, ``~/x/y``) shown by its last part only.
const ABSOLUTE_PATH = /(^|[\s=:'"(])((?:~|\/)[^\s'"():;|&]*\/([^\s'"():;|&/]+))/g;

export function shortStep(tool: ToolStep): string {
  let text = tool.input.trim();
  if (tool.tool === "Bash") {
    text = text
      .replace(/^(cd\s+\S+\s*(&&|;)\s*)+/, "")
      .replace(/^([A-Za-z_][A-Za-z0-9_]*=\S*\s+)+/, "") // leading VAR=value settings say nothing (and may be secret)
      .replace(/^\S*python3?(\.\d+)?\s+-m\s+/, "")
      .replace(/^\S*\/(\S+)/, "$1");
    const ranged = /^sed\s+-n\s+'?(\d+),(\d+)p'?\s+(\S+)\s*$/.exec(text);
    const read = /^(cat|head|tail|less|more)(\s+-\S+)*\s+(\S+)\s*$/.exec(text);
    if (ranged) text = `reads ${baseName(ranged[3])} lines ${ranged[1]}–${ranged[2]}`;
    else if (read) text = `reads ${baseName(read[3])}`;
    else text = text.replace(ABSOLUTE_PATH, (_match, lead: string, _path: string, last: string) => `${lead}${last}`);
  } else if (FILE_TOOLS.has(tool.tool)) {
    text = baseName(text);
  } else {
    text = text.replace(ABSOLUTE_PATH, (_match, lead: string, _path: string, last: string) => `${lead}${last}`);
  }
  return text.length > 60 ? `${text.slice(0, 59)}…` : text;
}
