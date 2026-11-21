import { getSpecPath, type ResearchPolicySpec } from "./researchPolicySpecHelpers";

function valueAt(spec: ResearchPolicySpec, path: string[]): string {
  const value = getSpecPath(spec, path);
  return typeof value === "number" || typeof value === "string" ? String(value) : "—";
}

// Key limits of the profile version being edited, shown at the top of the drawer.
export function ResearchProfileMetrics({ spec }: { spec: ResearchPolicySpec }) {
  const metrics = [
    {
      label: "Sources (min / target / max)",
      value: `${valueAt(spec, ["research_strategy", "min_source_count"])} / ${valueAt(spec, ["research_strategy", "target_source_count"])} / ${valueAt(spec, ["research_strategy", "max_source_count"])}`,
    },
    { label: "Target pages", value: valueAt(spec, ["output_policy", "target_pages", "target"]) },
    { label: "Child agents", value: valueAt(spec, ["delegation_policy", "max_child_agents"]) },
    { label: "Archive folder", value: valueAt(spec, ["evidence_archive", "workspace_folder"]) },
  ];
  return (
    <div className="research-metrics">
      {metrics.map((metric) => (
        <div key={metric.label} className="research-metrics__item">
          <span className="research-metrics__label">{metric.label}</span>
          <strong className="research-metrics__value">{metric.value}</strong>
        </div>
      ))}
    </div>
  );
}
