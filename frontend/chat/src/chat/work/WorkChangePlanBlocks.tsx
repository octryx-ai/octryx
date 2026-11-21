// Building blocks of the Change Plan view: titled blocks, string lists, compact objects and the version delta.

import type { WorkChangePlan } from "./workChangePlanTypes";
import { compactDetails, compactLabel } from "./workChangePlanLabels";

export function PlanBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="work-change-plan__block">
      <h4>{title}</h4>
      {children}
    </div>
  );
}

export function StringList({ values, emptyText }: { values: string[]; emptyText: string }) {
  if (values.length === 0) return <p>{emptyText}</p>;
  return (
    <ul>
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}

export function CompactObjects({ values, emptyText }: { values: Array<Record<string, unknown>>; emptyText: string }) {
  if (values.length === 0) return <p>{emptyText}</p>;
  return (
    <div className="work-change-plan__objects">
      {values.map((value, index) => (
        <article key={`${index}-${compactLabel(value)}`}>
          <strong>{compactLabel(value)}</strong>
          <span>{compactDetails(value)}</span>
        </article>
      ))}
    </div>
  );
}

export function VersionDelta({ current, previous }: { current: WorkChangePlan; previous: WorkChangePlan }) {
  const changed = [
    ["request", current.understood_request, previous.understood_request],
    ["questions", current.open_questions, previous.open_questions],
    ["repositories", current.affected_repositories, previous.affected_repositories],
    ["validation", current.validation_plan, previous.validation_plan],
    ["risks", current.security_risks, previous.security_risks],
    ["reviewers", current.reviewer_recommendations, previous.reviewer_recommendations],
  ]
    .filter(([, a, b]) => JSON.stringify(a) !== JSON.stringify(b))
    .map(([label]) => String(label));
  return (
    <div className="work-change-plan__delta">
      <strong>Changes since v{previous.version}</strong>
      <span>{changed.length > 0 ? changed.join(", ") : "No content changes detected."}</span>
    </div>
  );
}
