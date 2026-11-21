// The current turn of a device job as the chat shows it: streamed text, tool cards and live refusals.
import type { DeviceJob } from "./deviceJobTypes";
import { readRemedy, type Remedy } from "./remedyModel";

const text = (value: unknown): string => (typeof value === "string" ? value : "");

export type TurnItem =
  | { kind: "text"; key: string; text: string }
  | { kind: "tool"; key: string; tool: string; preview: string; status: "running" | "done" | "error"; output: string;
      /** A refusal's one-click fix (`tool_result.remedy`, or a live `tool_denied` event; backend). */
      remedy?: Remedy | null;
      /** A live `tool_denied` event already marked this card. */
      denied?: boolean };

export type TurnView = { items: TurnItem[]; finished: Record<string, unknown> | null; accepted: boolean };

type ToolItem = Extract<TurnItem, { kind: "tool" }>;
export type TurnBlock = Extract<TurnItem, { kind: "text" }> | { kind: "tools"; key: string; tools: ToolItem[] };

/** Consecutive tool cards become one block, so the card folds them into one line as the chat does. */
export function turnBlocks(items: TurnItem[]): TurnBlock[] {
  const blocks: TurnBlock[] = [];
  for (const item of items) {
    const last = blocks[blocks.length - 1];
    if (item.kind === "text") blocks.push(item);
    else if (last && last.kind === "tools") last.tools.push(item);
    else blocks.push({ kind: "tools", key: `b${item.key}`, tools: [item] });
  }
  return blocks;
}

/** The current turn's stream: text (deltas merged until the final text arrives) and tool cards. */
export function turnView(job: DeviceJob): TurnView {
  const items: TurnItem[] = [];
  const tools = new Map<string, Extract<TurnItem, { kind: "tool" }>>();
  let streaming: { kind: "text"; key: string; text: string } | null = null;
  let finished: Record<string, unknown> | null = null;
  let accepted = false;
  for (const event of job.events) {
    if (job.turnId && text(event.body.turn_id) !== job.turnId) continue;
    if (event.type === "job_accepted") accepted = true;
    if (event.type === "turn_finished") finished = event.body;
    if (event.type !== "job_event") continue;
    const kind = text(event.body.kind);
    if (kind === "text_delta") {
      if (!streaming) {
        streaming = { kind: "text", key: `t${event.seq}`, text: "" };
        items.push(streaming);
      }
      streaming.text += text(event.body.text);
    } else if (kind === "text") {
      if (streaming) streaming.text = text(event.body.text);
      else items.push({ kind: "text", key: `t${event.seq}`, text: text(event.body.text) });
      streaming = null;
    } else if (kind === "tool_use") {
      streaming = null;
      const card = { kind: "tool" as const, key: `u${event.seq}`, tool: text(event.body.tool), status: "running" as const,
        preview: text(event.body.input_preview), output: "" };
      tools.set(text(event.body.tool_use_id), card);
      items.push(card);
    } else if (kind === "tool_result") {
      const card = tools.get(text(event.body.tool_use_id));
      if (card) {
        card.status = event.body.is_error === true ? "error" : "done";
        card.output = text(event.body.output);
        card.remedy = readRemedy(event.body.remedy);
      }
    }
  }
  applyDenials(job, items);
  return { items, finished, accepted };
}

/** Each live refusal of this turn marks the latest card of its tool that has no remedy yet: refused, its message
 * as output until the `tool_result` brings the device's own text, and its remedy. */
function applyDenials(job: DeviceJob, items: TurnItem[]) {
  for (const denial of job.denials ?? []) {
    if (job.turnId && denial.turnId && denial.turnId !== job.turnId) continue;
    const card = [...items].reverse().find((item): item is ToolItem => item.kind === "tool" && item.tool === denial.tool
      && !item.remedy && !item.denied);
    if (!card) continue;
    card.denied = true;
    card.status = "error";
    if (!card.output) card.output = denial.message;
    if (!card.remedy) card.remedy = denial.remedy;
  }
}
