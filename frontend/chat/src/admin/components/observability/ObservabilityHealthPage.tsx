import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { formatTime, readErrorMessage } from "./obFormat";
import { Badge, type ProjectOption } from "./obUi";
import { HEALTH_BADGES, type HealthLink, type HealthPayload } from "./healthModel";
import "./observability.css";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

// Observability → Health: a roll-up only; every row links to the screen that owns the detail.
export function ObservabilityHealthPage({ readJson }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const [data, setData] = useState<HealthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await readJson<HealthPayload>("/api/v1/observability/health"));
      setError(null);
    } catch (loadError) {
      setError(readErrorMessage(loadError, "Health could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [readJson]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (link: HealthLink) => {
    if (link?.tab) openAdminTab(link.tab);
    else if (link?.href) window.location.assign(link.href);
  };

  return (
    <div className="ob-page" data-testid="observability-health">
      <div className="ob-between">
        <span />
        <div className="ob-row">
          <span className="ob-muted">{data ? `Checked ${formatTime(data.checked_at)}` : ""}</span>
          <button type="button" className="admin-panel__action-btn" disabled={loading} onClick={() => void load()}>Refresh</button>
        </div>
      </div>
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      {(data?.groups ?? []).map((group) => (
        <div className="admin-panel__card" key={group.key}>
          <div className="admin-panel__section-header">
            <span>{group.label}</span>
            <span className="ob-muted">Details: {group.owner}</span>
          </div>
          <table className="admin-panel__table ob-cards">
            <thead><tr><th>Component</th><th>Status</th><th>Since</th><th>Last check</th><th>Detail</th></tr></thead>
            <tbody>
              {group.rows.map((row) => (
                <tr key={row.component} className={row.link ? "ob-row-button" : undefined} tabIndex={row.link ? 0 : undefined}
                  title={row.link ? `Open ${row.link.label}` : undefined}
                  onClick={() => open(row.link)} onKeyDown={(event) => { if (event.key === "Enter") open(row.link); }}>
                  <td data-label="Component"><span className="ob-name">{row.component}</span></td>
                  <td data-label="Status"><Badge tone={HEALTH_BADGES[row.status][0]}>{HEALTH_BADGES[row.status][1]}</Badge></td>
                  <td data-label="Since">{row.since ? formatTime(row.since) : "–"}</td>
                  <td data-label="Last check" className="admin-panel__cell--muted">{formatTime(row.last_check)}</td>
                  <td data-label="Detail" className="admin-panel__cell--muted">{row.detail || "–"}</td>
                </tr>
              ))}
              {!group.rows.length ? (
                <tr><td colSpan={5} className="admin-panel__cell--muted">Nothing to check in this group.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
