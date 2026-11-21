// Text labels of a Change Plan: compact object lines and the type, author and usage of a plan.

import type { WorkChangePlan } from "./workChangePlanTypes";

export function compactLabel(value: Record<string, unknown>): string {
  return String(
    value.kind
      || value.repository_name
      || value.branch_name
      || value.command
      || value.risk
      || value.type
      || value.display_name
      || "Item",
  );
}

export function compactDetails(value: Record<string, unknown>): string {
  const entries = Object.entries(value)
    .filter(([key]) => key !== "kind")
    .map(([key, entry]) => `${key}: ${stringify(entry)}`)
    .filter((entry) => entry.length < 220);
  return entries.join(" · ") || "-";
}

export function planTypeLabel(plan: WorkChangePlan): string {
  const planType = typeof plan.evidence?.plan_type === "string" ? plan.evidence.plan_type : "unknown";
  return `Type: ${planType.replaceAll("_", " ")}`;
}

export function planAuthorLabel(plan: WorkChangePlan): string {
  const author = typeof plan.evidence?.author === "string" ? plan.evidence.author : "system";
  const runtime = plan.evidence?.runtime;
  const model = runtime && typeof runtime === "object" && "model" in runtime ? String(runtime.model || "") : "";
  return model ? `Author: ${author} · ${model}` : `Author: ${author}`;
}

export function planUsageLabel(plan: WorkChangePlan): string {
  const summary = plan.evidence?.usage_summary;
  const usage = summary && typeof summary === "object" ? summary : plan.evidence?.usage;
  if (!usage || typeof usage !== "object") return "Usage: not captured";
  const tokensIn = numberField(usage, ["tokens_in", "prompt_tokens", "inputTokens"]);
  const tokensOut = numberField(usage, ["tokens_out", "completion_tokens", "outputTokens"]);
  const total = numberField(usage, ["total_tokens", "totalTokens"]) || tokensIn + tokensOut;
  const cost = numberField(usage, ["estimated_cost", "cost"]);
  const costLabel = cost > 0 ? ` · $${cost.toFixed(6)}` : "";
  return total > 0 ? `Usage: ${total.toLocaleString()} tokens${costLabel}` : "Usage: captured";
}

function numberField(value: object, keys: string[]): number {
  for (const key of keys) {
    if (key in value) {
      const numeric = Number((value as Record<string, unknown>)[key]);
      if (Number.isFinite(numeric)) return numeric;
    }
  }
  return 0;
}

function stringify(value: unknown): string {
  if (Array.isArray(value)) return value.map(stringify).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "-");
}
