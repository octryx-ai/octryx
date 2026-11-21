import { useCallback, useEffect, useState } from "react";

import { DataTable } from "../../../layout/DataTable";
import { listFunctions, loadAudit } from "./workRolesApi";
import { auditChanges, auditSentence, errorView, type ErrorView } from "./workRolesModel";
import { Card, ErrorLine } from "./WorkRolesParts";
import type { AuditEvent, WorkFunction } from "./workRolesTypes";
import "./workRoles.css";

const PAGE = 50;

function when(at: string): string {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? at : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// Admin › People & sign-in › Roles & functions › Changes: every edit of roles, functions, assignments, the switch
// and the SSO mapping (contract §3.5), newest first, with "Show older" following next_before.
export function WorkRolesAuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [functions, setFunctions] = useState<WorkFunction[]>([]);
  const [error, setError] = useState<ErrorView | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchPage = useCallback(async (before: string | null) => {
    setBusy(true);
    try {
      const page = await loadAudit({ before, limit: PAGE });
      setEvents((current) => (before && current ? [...current, ...page.events] : page.events));
      setNext(page.next_before);
      setError(null);
    } catch (failure) {
      setEvents((current) => current ?? []);
      setError(errorView(failure, "The change log could not be loaded."));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void fetchPage(null);
    listFunctions().then(setFunctions).catch(() => undefined);
  }, [fetchPage]);

  return (
    <div className="wr-page" data-testid="work-roles-audit">
      <ErrorLine error={error} />
      <Card title="Changes to roles" meta="Who changed which role, function, assignment or setting, with the reason and what it was before.">
        <DataTable<AuditEvent>
          label="Role changes" rows={events ?? []} loading={events === null} loadingLabel="changes" rowKey={(event) => event.id}
          empty={{ text: "No change yet." }}
          columns={[
            { key: "at", header: "When", nowrap: true, width: "11rem", render: (event) => <span className="wr-muted">{when(event.at)}</span> },
            { key: "who", header: "Who", nowrap: true, width: "10rem", render: (event) => event.actor.label },
            { key: "what", header: "What", grow: true, minWidth: "18rem", render: (event) => {
              const changes = auditChanges(event, functions);
              return (
                <span className="wr-audit-what">
                  <span>{auditSentence(event)}</span>
                  {changes.map((line) => <span key={line} className="wr-audit-change">{line}</span>)}
                </span>
              );
            } },
            { key: "reason", header: "Reason", clip: "18rem", render: (event) => event.reason
              ? <span title={event.reason}>{event.reason}</span> : <span className="wr-muted">No reason given</span> },
          ]}
        />
        {next ? (
          <div className="wr-more">
            <button type="button" className="ds-btn" disabled={busy} data-testid="audit-older" onClick={() => void fetchPage(next)}>
              {busy ? "Loading…" : "Show older changes"}
            </button>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
