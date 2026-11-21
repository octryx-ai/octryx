import type { ReactNode } from "react";
import "./adminDetailFacts.css";

export type AdminDetailFact = { label: string; value: ReactNode };

// The read-only facts of one object in its side panel (Channels, Schedulers, Webhooks): label left, value right.
// Empty values are left out, so a panel never shows a row of dashes.
export function AdminDetailFacts({ facts, testId }: { facts: AdminDetailFact[]; testId?: string }) {
  const shown = facts.filter((fact) => fact.value !== null && fact.value !== undefined && fact.value !== "");
  return (
    <dl className="admin-detail-facts" data-testid={testId}>
      {shown.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}
