// The client cannot see which stage runs, so it names the search as a whole.

export const SLOW_AFTER_SECONDS = 10;

export function searchProgressText(elapsedSeconds: number): string {
  if (elapsedSeconds < 1) return "Searching the Workspace's sources…";
  if (elapsedSeconds < SLOW_AFTER_SECONDS) return `Searching the Workspace's sources · ${elapsedSeconds} s`;
  return `Still searching · ${elapsedSeconds} s. This takes longer than usual; the search keeps running.`;
}

export function answerProgressText(elapsedSeconds: number): string {
  return elapsedSeconds < 1 ? "Writing a short answer…" : `Writing a short answer · ${elapsedSeconds} s`;
}

const STAGE_LABELS: Record<string, string> = {
  lexical: "keywords",
  embed: "reading the question",
  vector_query: "meaning",
  vector: "meaning",
  rerank: "ranking",
  resolve: "citations",
  origin: "sources",
};

type Timings = Record<string, unknown>;

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;

// Measured apart, embedding and index query make up the combined vector stage, which is then left out.
export function searchTimingText(timings: Timings | null | undefined): string {
  if (!timings) return "";
  const nested = timings.stages && typeof timings.stages === "object" ? (timings.stages as Timings) : null;
  const values = nested ?? timings;
  const split = finite(values.vector_query);
  const seconds = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const stages = Object.entries(values)
    .filter((entry): entry is [string, number] => entry[0] !== "total" && finite(entry[1]))
    .filter(([key]) => !(split && key === "vector"))
    .map(([key, ms]) => `${STAGE_LABELS[key] ?? key.replace(/[_-]+/g, " ")} ${seconds(ms)}`);
  const total = timings.total;
  if (!finite(total)) return stages.length ? `Search stages: ${stages.join(" · ")}` : "";
  return stages.length ? `Found in ${seconds(total)} (${stages.join(" · ")})` : `Found in ${seconds(total)}`;
}

export function searchTimingSummary(timings: Timings | null | undefined): string {
  const total = timings?.total;
  if (!finite(total)) return "";
  return `Found in ${(total / 1000).toFixed(total < 10_000 ? 1 : 0)} s`;
}
