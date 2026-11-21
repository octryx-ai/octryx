import { useEffect, useState } from "react";
import { connectorsApi } from "../connectorsApi";
import type { ConnectorConfig } from "../connectorTypes";
import { StatusLabel } from "../../../../layout/StatusLabel";
import { TimeText } from "../../../utils/TimeText";
import { restRefusalOf } from "./restSourceRefusals";
import { restSampleView } from "./restSourceSample";
import type { Refusal } from "./restSourceRefusals";
import type { RestSampleView } from "./restSourceSample";
import { RestAclNotice } from "./RestSourceStatus";

// The dry run of a REST source draft (`POST …/connectors/{key}/sample`): one page mapped to items as a sync would,
// restricted items the author may not read shown as hidden with the reason, dropped and skipped counts, and per visible
// item the server's masked excerpt of what will be ingested. Nothing is saved or indexed.

type Draft = { key: string; config: ConnectorConfig } | { problem: string };

export function RestSourceDryRun({ workspaceId, draft, draftKey, onRefused, isPlatformAdmin }: {
  workspaceId: string;
  isPlatformAdmin: boolean;
  // Builds the request from the form; a problem blocks the dry run and is shown at its fields by the form.
  draft: () => Draft;
  // Changes whenever the form changes, so an old result never stands next to new settings.
  draftKey: string;
  onRefused: (refusal: Refusal | null) => void;
}) {
  const [view, setView] = useState<RestSampleView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setView(null); setError(null); }, [draftKey]);

  async function run() {
    const built = draft();
    if ("problem" in built) { setView(null); setError(built.problem); return; }
    setBusy(true);
    setError(null);
    onRefused(null);
    try {
      setView(restSampleView(await connectorsApi.sample(workspaceId, built.key, built.config)));
    } catch (failure) {
      const refusal = restRefusalOf(failure);
      setView(null);
      setError(refusal.text);
      onRefused(refusal);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ds-form-section rest-source__dry-run" aria-label="Dry run" data-testid="rest-source-dry-run">
      <div className="rest-source__head">
        <span className="ds-form-section__title">Dry run</span>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void run()}
          data-testid="rest-source-dry-run-start">{busy ? "Reading…" : "Run dry run"}</button>
      </div>
      <p className="rst-muted">Reads one page as the chosen role and maps it like a sync. It stores nothing and indexes nothing; the API calls are audited.</p>
      {error ? <p className="rst-error" role="alert">{error}</p> : null}
      {view ? <DryRunResult view={view} workspaceId={workspaceId} isPlatformAdmin={isPlatformAdmin} /> : null}
    </section>
  );
}

function DryRunResult({ view, workspaceId, isPlatformAdmin }: { view: RestSampleView; workspaceId: string; isPlatformAdmin: boolean }) {
  const shown = view.rows.length;
  return (
    <div className="rest-source__result" data-testid="rest-source-dry-run-result">
      <dl className="rest-source__facts">
        <div><dt>Read</dt><dd>{view.listed}{view.lastPage ? "" : " (first page)"}</dd></div>
        <div><dt>Hidden from you</dt><dd>{view.hidden}</dd></div>
        <div><dt>Skipped</dt><dd>{view.skipped}{view.skippedReasons.length ? <span>{view.skippedReasons.join(" · ")}</span> : null}</dd></div>
        <div><dt>Outside the role's scope</dt><dd>{view.dropped}</dd></div>
      </dl>
      {view.role ? <p className="rst-muted">Read as <b>{view.role}</b>{shown < view.listed ? `. The first ${shown} items are shown.` : "."}</p> : null}
      {shown ? (
        <ul className="rest-source__items" data-testid="rest-source-items">
          {view.rows.map((row) => (
            <li key={row.id} className={row.hidden ? "is-hidden" : undefined} data-testid={row.hidden ? "rest-source-item-hidden" : "rest-source-item"}>
              <div className="rest-source__item-head">
                {row.hidden ? <StatusLabel label="Hidden" tone="neutral" />
                  : row.url ? <a href={row.url} target="_blank" rel="noreferrer noopener" className="rest-source__item-title">{row.title}</a>
                    : <span className="rest-source__item-title">{row.title}</span>}
                <code className="rst-mono">{row.id}</code>
                {row.updated ? <span className="rst-muted"><TimeText value={row.updated} mode="date" /></span> : null}
              </div>
              {row.excerpt ? <p className="rest-source__excerpt" data-testid="rest-source-excerpt">{row.excerpt}</p>
                : row.excerptNote ? <p className="rest-source__excerpt rst-muted">{row.excerptNote}</p> : null}
              <div className="rst-muted">{row.who}</div>
            </li>
          ))}
        </ul>
      ) : <p className="rst-muted">No record of this page could be mapped.</p>}
      {view.members ? (
        <p className="rst-muted">The first item would be found by {view.members.admitted} member{view.members.admitted === 1 ? "" : "s"} of this Workspace
          {view.members.unmapped ? `; ${view.members.unmapped} more hold the role but have no usable address` : ""}.</p>
      ) : null}
      <RestAclNotice acl={view.acl} workspaceId={workspaceId} isPlatformAdmin={isPlatformAdmin} newTab />
    </div>
  );
}
