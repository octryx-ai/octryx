// The run's Tokens view (see where tokens could be saved): per phase a stacked bar of what filled the
// context, the top consumers and the savings hints. Everything comes from GET /workflow-runs/{id}/token-profile;
// categories, labels and hint texts are the server's (its rules catalog), nothing is decided here.

export type TokenCategory = { key: string; label: string };
export type TokenBasis = "measured" | "estimated" | "mixed";

export type TokenPhase = {
  phase: string;
  turns: number;
  calls: number;
  basis: TokenBasis;
  categories: Record<string, number>;
  by_tool: Record<string, number>;
  cache: { read: number; write: number; uncached: number; output: number };
};

export type TokenConsumer = {
  tool: string;
  label: string;
  count: number;
  max_kb: number;
  total_kb: number;
  tokens: number;
  estimated: boolean;
  at_least: boolean;
  phase: string;
};

export type TokenHint = { rule: string; text: string; tokens: number; phase: string; estimated: boolean };

export type TokenProfile = {
  run_id: string;
  basis: TokenBasis;
  categories: TokenCategory[];
  totals: { read: number; write: number; uncached: number; output: number; input: number };
  phases: TokenPhase[];
  consumers: TokenConsumer[];
  hints: TokenHint[];
};

export function tokenProfilePath(runId: string): string {
  return `/api/v1/workflow-runs/${encodeURIComponent(runId)}/token-profile`;
}

// 1234 → "1.2k", 2_500_000 → "2.5M": tokens at a glance.
export function tokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(Math.max(0, Math.round(value)));
}

export const BASIS_TEXT: Record<TokenBasis, string> = {
  measured: "Measured per model call.",
  estimated: "Estimated: this run ran before calls were measured. Tool results count up to 4 KB each, so large ones show as at least that.",
  mixed: "Partly measured: the earlier turns of this run are estimates.",
};

export type BarSegment = { key: string; label: string; tokens: number; share: number };

// One phase's bar: its categories in the server's order, each with its share of the phase's tokens (empty ones left
// out), and the phase's share of the largest phase, so the bars compare between phases.
export function phaseBars(profile: TokenProfile): { phase: TokenPhase; total: number; width: number; segments: BarSegment[] }[] {
  const totals = profile.phases.map((phase) => Object.values(phase.categories).reduce((sum, value) => sum + value, 0));
  const largest = Math.max(1, ...totals);
  return profile.phases.map((phase, index) => {
    const total = totals[index];
    const segments = profile.categories
      .map((category) => ({ key: category.key, label: category.label, tokens: phase.categories[category.key] ?? 0 }))
      .filter((segment) => segment.tokens > 0)
      .map((segment) => ({ ...segment, share: total ? segment.tokens / total : 0 }));
    return { phase, total, width: total / largest, segments };
  });
}

export function consumerText(consumer: TokenConsumer): string {
  const size = `${consumer.at_least ? "≥" : ""}${consumer.max_kb} KB`;
  const times = consumer.count > 1 ? ` × ${consumer.count}` : "";
  return `${size}${times} · ${tokenCount(consumer.tokens)} tokens${consumer.estimated ? " (estimate)" : ""}`;
}

export function phaseFacts(phase: TokenPhase): string {
  const turns = `${phase.turns} turn${phase.turns === 1 ? "" : "s"}`;
  // Calls are counted only when measured; an estimate guesses them, so it does not show a number.
  const calls = phase.basis === "measured" ? ` · ${phase.calls} call${phase.calls === 1 ? "" : "s"}` : "";
  const cached = phase.cache.read + phase.cache.write + phase.cache.uncached;
  const readShare = cached ? Math.round((phase.cache.read / cached) * 100) : 0;
  return `${turns}${calls} · ${readShare}% from the cache${phase.basis === "measured" ? "" : " · estimate"}`;
}

export function totalsText(profile: TokenProfile): string {
  const { input, read, write, uncached, output } = profile.totals;
  return `${tokenCount(input)} input (${tokenCount(read)} cache read, ${tokenCount(write)} cache write, ${tokenCount(uncached)} uncached) · ${tokenCount(output)} output`;
}
