// Pure presentation of the structured graph status and the Handbook vs. reality report.
import type {
  HandbookReport, StructuredBuild, StructuredCitation, StructuredLayer, StructuredStatus, VariantItem,
} from "./structuredGraphApi";

export const LAYER_LABELS: Record<StructuredLayer, string> = {
  manual: "Manual",
  configuration: "Configuration",
  operations: "Operations",
};

// Where a citation points, in the words a reader checks it with: page and section, or file line.
export function citationLocation(citation: StructuredCitation | null | undefined): string {
  if (!citation) return "citation not available to you";
  const parts = [citation.source_title || citation.citation || "source"];
  if (citation.page) parts.push(`p. ${citation.page}`);
  if (citation.section) parts.push(`§ ${citation.section}`);
  if (citation.line) parts.push(`line ${citation.line}`);
  return parts.join(" · ");
}

export function buildSummary(build: StructuredBuild | undefined): string {
  if (!build) return "No structured graph has been built for this workspace yet.";
  const layers = build.layers.map((layer) => LAYER_LABELS[layer] ?? layer).join(", ");
  if (build.state === "pending") return `Build of ${layers} is queued.`;
  if (build.state === "running" && build.lease_expired) {
    return `Build of ${layers} is waiting to be resumed (its runner stopped or handed it back).`;
  }
  if (build.state === "running") return `Build of ${layers} is running.`;
  if (build.state === "failed") return `Build of ${layers} failed (${build.failure ?? "unknown reason"}).`;
  if (!build.report) return `Last build of ${layers} completed.`;
  const extracted = Object.values(build.report.layers ?? {}).reduce((sum, item) => sum + (item.extracted ?? 0), 0);
  const failed = Object.values(build.report.layers ?? {}).reduce((sum, item) => sum + (item.failed ?? 0), 0);
  const failures = failed ? `, ${failed} unreadable` : "";
  return `Last build of ${layers} completed: ${extracted} source revisions extracted${failures}.`;
}

// The manual build runner's health, from its last recorded run.
export function runnerSummary(runner: StructuredStatus["runner"] | undefined): string {
  if (!runner) return "The build runner has not reported yet.";
  const at = runner.updated_at ?? runner.completed_at ?? "unknown time";
  if (runner.status === "failed") return `The build runner reported a problem at ${at} (${runner.failure ?? "unknown"}).`;
  return `The build runner last reported at ${at}.`;
}

export function layerRows(status: StructuredStatus | null): Array<{ layer: StructuredLayer; label: string; text: string }> {
  if (!status) return [];
  const visible = status.layers;
  return (Object.keys(LAYER_LABELS) as StructuredLayer[]).map((layer) => {
    if (!visible) return { layer, label: LAYER_LABELS[layer], text: "counts are shown to workspace authors" };
    const counts = visible[layer] ?? { revisions: 0, nodes: 0, edges: 0 };
    const text = counts.revisions
      ? `${counts.revisions} sources · ${counts.nodes} nodes · ${counts.edges} relationships`
      : "not built";
    return { layer, label: LAYER_LABELS[layer], text };
  });
}

export function toggleLayer(selected: StructuredLayer[], layer: StructuredLayer): StructuredLayer[] {
  const next = selected.includes(layer) ? selected.filter((item) => item !== layer) : [...selected, layer];
  return (Object.keys(LAYER_LABELS) as StructuredLayer[]).filter((item) => next.includes(item));
}

export function reportNotice(report: HandbookReport | null): string | null {
  if (!report) return null;
  if (report.state === "not_built") return "Build the configuration layer (and the manual layer) to compare them.";
  if (report.state === "no_manual") return "No manual parameters are built yet: build the manual layer to compare against it.";
  return null;
}

export function displayValue(value: string, redacted: boolean): string {
  return redacted ? "[redacted]" : value;
}

export function reportSummary(report: HandbookReport): string {
  const c = report.counts;
  const n = (key: string) => c[key] ?? 0;
  return `${n("configured_settings")} settings match a documented parameter · `
    + `${n("undocumented_in_known_section")} undocumented in sections the manual knows · `
    + `${n("unknown_section")} sections unknown to the manual (${n("unknown_section_settings")} keys) · `
    + `${n("deviations")} deviate from the default · ${n("unresolved_placeholders")} unresolved placeholders · `
    + `${n("inconsistencies")} differ across components · ${n("documented_unused")} documented but never set`
    + `${report.truncated ? " (lists show the first items)" : ""}.`;
}

// "also server.ini-test (test): 600" — a variant's own value next to the base file's finding.
export function variantsNote(variants: VariantItem[] | undefined): string | null {
  if (!variants || !variants.length) return null;
  return "also " + variants.map((item) => {
    const value = item.resolved_value ? `${item.value} = ${item.resolved_value}` : item.value;
    return `${item.path} line ${item.line}: ${value}`;
  }).join("; ");
}
