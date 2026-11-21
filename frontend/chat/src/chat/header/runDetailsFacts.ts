import type { ChatMessage } from "../../chatThreadTypes";

// Run details: names the model(s) the thread's answers actually came from — the
// label each answer carries (`runtimeLabel`, else provider / model, else its turn trace) — and the current selection
// separately, as label/value pairs in words. Pure: no React.

export type RunFact = { key: string; label: string; value: string; title?: string };

/** The model an answer came from, as its message header names it ("bedrock / anthropic.claude-haiku-5-5"). */
export function answerModelLabel(message: ChatMessage): string {
  const runtime = (message.runtimeLabel || "").trim();
  if (runtime) return runtime;
  const model = (message.model || "").trim();
  const provider = (message.providerName || "").trim();
  if (model) return provider && provider !== model ? `${provider} / ${model}` : model;
  const traceModel = (message.turnTrace?.model || "").trim();
  const traceProvider = (message.turnTrace?.provider || "").trim();
  if (traceModel) return traceProvider ? `${traceProvider} / ${traceModel}` : traceModel;
  return "";
}

/** Every model the loaded answers came from, once each, in the order they were first used. */
export function modelsUsed(messages: ChatMessage[] | null | undefined): string[] {
  const used: string[] = [];
  for (const message of messages ?? []) {
    if (message.role !== "assistant") continue;
    const label = answerModelLabel(message);
    if (label && !used.includes(label)) used.push(label);
  }
  return used;
}

/** The model of the latest answer that names one; "" when no answer does. */
export function lastModelUsed(messages: ChatMessage[] | null | undefined): string {
  const list = messages ?? [];
  for (let index = list.length - 1; index >= 0; index -= 1) {
    if (list[index].role !== "assistant") continue;
    const label = answerModelLabel(list[index]);
    if (label) return label;
  }
  return "";
}

/** The model part of "provider / model" for the one-line header ("anthropic.claude-haiku-5-5"). */
export function modelShortLabel(label: string): string {
  const value = (label || "").trim();
  const slash = value.lastIndexOf(" / ");
  return slash > 0 ? value.slice(slash + 3) : value;
}

const MODEL_VENDORS = /^(?:[a-z]{2}\.)?(?:anthropic|amazon|meta|mistral|cohere|ai21|google|openai|deepseek|qwen|writer)\./i;
const MODEL_ACRONYMS: Record<string, string> = { gpt: "GPT", oss: "OSS", llm: "LLM" };

/**
 * A model id in words for the one-line header: "anthropic.claude-haiku-5-5" → "Claude Haiku 5.5",
 * "us.anthropic.claude-sonnet-4-5-20250929-v1:0" → "Claude Sonnet 4.5", "gemma-4" → "Gemma 4". A label that is already
 * words ("Automatic · Gemma 4") stays as it is; the raw id remains the tooltip.
 */
export function modelDisplayName(id: string): string {
  const raw = (id || "").trim();
  if (!raw || /\s/.test(raw)) return raw;
  const name = (raw.split("/").pop() || raw)
    .replace(MODEL_VENDORS, "")
    .replace(/[-_:]v\d+(?::\d+)?$/i, "")
    .replace(/-\d{8}$/, "");
  const words: string[] = [];
  for (const part of name.split(/[-_]+/).filter(Boolean)) {
    const last = words[words.length - 1];
    if (/^\d+$/.test(part) && last && /^\d+(?:\.\d+)*$/.test(last)) words[words.length - 1] = `${last}.${part}`;
    else words.push(part);
  }
  if (!words.length) return raw;
  return words.map((word) => MODEL_ACRONYMS[word.toLowerCase()] ?? (/^\d/.test(word) ? word : word.charAt(0).toUpperCase() + word.slice(1))).join(" ");
}

/** "Route · Diagnosis" → "Diagnosis": the fact's label already says what it is. */
export function withoutPrefix(value: string, prefix: string): string {
  const text = (value || "").trim();
  const head = `${prefix} · `;
  return text.toLowerCase().startsWith(head.toLowerCase()) ? text.slice(head.length) : text;
}

/** The thread's state in one word where both labels say the same ("Active · Done" → "Done"). */
export function runStatusText(threadStatus: string, runStatus: string): string {
  const thread = (threadStatus || "").trim();
  const run = (runStatus || "").trim();
  if (!thread || thread === "Active" || thread === "Ready" || thread.toLowerCase() === run.toLowerCase()) return run || thread;
  if (!run || run === "Ready") return thread;
  return `${thread} · ${run}`;
}

export function runDetailsFacts({
  used, selection, hasSession, status, thinking, route, routeDetail, workflow,
}: {
  used: string[];
  selection: string;
  hasSession: boolean;
  status: string;
  thinking: string;
  route: string;
  routeDetail?: string;
  workflow: string;
}): RunFact[] {
  const facts: RunFact[] = [];
  if (used.length) {
    facts.push({ key: "used", label: used.length === 1 ? "Model used" : "Models used", value: used.join(", ") });
  }
  if (selection) {
    // Before the first answer the selection is simply the model; in a thread it is what is selected now, which is
    // not necessarily what answered ("Automatic" picks a model per message).
    facts.push({
      key: "selection", label: hasSession ? "Selected model" : "Model", value: selection,
      title: hasSession ? "The model selected for this chat now. The answers above name the model they came from." : undefined,
    });
  }
  if (status) facts.push({ key: "status", label: "Status", value: status });
  if (thinking) facts.push({ key: "thinking", label: "Thinking", value: thinking });
  const routeText = withoutPrefix(route, "Route");
  if (routeText) facts.push({ key: "route", label: "Route", value: routeText, title: routeDetail });
  const workflowText = withoutPrefix(workflow, "Workflow");
  if (workflowText) facts.push({ key: "workflow", label: "Workflow", value: workflowText });
  return facts;
}
