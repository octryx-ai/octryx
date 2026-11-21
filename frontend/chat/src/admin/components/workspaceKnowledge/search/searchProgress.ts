// What a running search says instead of an empty "Searching…": the stage and the elapsed seconds,
// and after ten seconds that it takes longer than usual. The stages are the server's order of work; the client
// cannot see which one runs, so it names the search as a whole until the answer arrives.

export const SLOW_AFTER_SECONDS = 10;

/** "Searching the Workspace's sources · 4 s", then the slow wording after ten seconds. */
export function searchProgressText(elapsedSeconds: number): string {
  if (elapsedSeconds < 1) return "Searching the Workspace's sources…";
  if (elapsedSeconds < SLOW_AFTER_SECONDS) return `Searching the Workspace's sources · ${elapsedSeconds} s`;
  return `Still searching · ${elapsedSeconds} s. This takes longer than usual; the search keeps running.`;
}

/** The answer's own stage after the hits arrived: "Writing a short answer · 3 s". */
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

/**
 * "Found in 3.2 s (keywords 0.2 s · reading the question 0.1 s · meaning 0.8 s · ranking 2.1 s)" from the server's
 * timings; "" without. Reads `{total, stages}` (the route) and the flat `{total, lexical, …}` form. When the
 * embedding and the index query are measured apart, the combined "vector" stage is left out (it is their sum).
 */
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

/** What the page shows: only "Found in 3.2 s"; the stage breakdown (searchTimingText) is its tooltip. */
export function searchTimingSummary(timings: Timings | null | undefined): string {
  const total = timings?.total;
  if (!finite(total)) return "";
  return `Found in ${(total / 1000).toFixed(total < 10_000 ? 1 : 0)} s`;
}
