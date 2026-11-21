import { actionBreakdown } from "./policyLifecycleModel";
import type { DraftImpact } from "./policyLifecycleModel";
import { serverDate } from "./policyEngineStatus";
import { formatDateTime } from "../../utils/dateTime";

// "Real traffic": what the open draft would have blocked in live traffic, from the draft
// shadow (evaluated next to the published set, never enforced). Per policy: the count, by action, how many users,
// and a few redacted samples. A policy not yet in the draft has nothing to show until it is saved.
export function DraftTraffic({ impact, policyId, inDraft }: { impact: DraftImpact | null; policyId: string; inDraft: boolean }) {
  if (!inDraft) {
    return <p className="admin-panel__hint" data-testid="draft-traffic-pending">Save it into the draft: while a draft exists it runs in shadow next to the published set, and what it would block in live traffic shows here.</p>;
  }
  if (!impact) return <p className="admin-panel__hint" data-testid="draft-traffic-unavailable">The draft shadow has no numbers yet.</p>;
  const mine = impact.policies[policyId];
  if (!mine) {
    return <p className="admin-panel__hint" data-testid="draft-traffic-none">In the last {impact.hours} h no live request would have been blocked by it.</p>;
  }
  return (
    <div className="policies__pane" data-testid="draft-traffic">
      <p className="policies__summary">
        In the last {impact.hours} h it would have blocked <b>{mine.count} request{mine.count === 1 ? "" : "s"}</b> ({actionBreakdown(mine)})
        {mine.principals ? <> by <b>{mine.principals} user{mine.principals === 1 ? "" : "s"}</b></> : null}.
      </p>
      {mine.samples.length ? (
        <details className="policies__advanced">
          <summary>Samples</summary>
          <ul className="policies__summary" data-testid="draft-traffic-samples">
            {mine.samples.map((sample, index) => (
              <li key={`${sample.time}-${index}`}>{sample.time ? formatDateTime(sample.time) : ""} · {sample.action} · <span className="admin-policy-inline-code">{sample.resource}</span> · {sample.principal}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
