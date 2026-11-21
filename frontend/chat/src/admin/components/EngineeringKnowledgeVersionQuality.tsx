// Engineering knowledge packs: the quality summary of a pack version.
import type { EngineeringKnowledgePackVersion } from "../types/engineeringKnowledgeTypes";
import { BlockersList } from "./EngineeringKnowledgeManifestView";

function qualityMetric(
  report: Record<string, unknown>,
  key: string,
  fallback: number | undefined,
) {
  const value = report[key];
  if (typeof value === "number" || typeof value === "string")
    return String(value);
  return fallback === undefined ? "—" : String(fallback);
}

export function VersionQualitySummary({
  version,
}: {
  version: EngineeringKnowledgePackVersion;
}) {
  const report = version.quality_report || {};
  const blockers =
    (report as { blockers?: Array<{ code?: string; message?: string }> })
      .blockers ?? [];
  return (
    <div
      style={{
        marginTop: "0.55rem",
        fontSize: "var(--ds-text-xs)",
        color: "var(--text-muted)",
      }}
    >
      Quality: archived sources{" "}
      {qualityMetric(report, "archived_source_count", version.source_count)} ·
      items{" "}
      {qualityMetric(report, "retrievable_item_count", version.item_count)} ·
      item evidence{" "}
      {qualityMetric(
        report,
        "item_evidence_complete_count",
        version.item_evidence_count,
      )}
      <BlockersList blockers={blockers} />
    </div>
  );
}
