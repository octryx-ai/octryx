// History table of Backup & restore: every backup and restore with when, what, Workspace, who and result.
import type { HistoryEntry } from "./backupRestoreModel";
import { DATA } from "./backupRestoreJobTypes";
import { formatDateTime } from "../utils/dateTime";

export function BackupHistoryTable({ history }: { history: HistoryEntry[] | null }) {
  return (
  <section className="admin-panel__card" aria-label="History">
    <div className="admin-panel__section-header"><span>History</span></div>
    <table className="admin-panel__table sk-cards" data-testid="backup-history">
      <thead><tr><th>When</th><th>What</th><th>Workspace</th><th>Who</th><th>Result</th><th /></tr></thead>
      <tbody>
        {history === null ? <tr><td colSpan={6} className="admin-panel__cell--muted">Loading…</td></tr>
          : history.length === 0 ? <tr><td colSpan={6} className="admin-panel__cell--muted">No backup or restore yet.</td></tr>
            : history.map((entry) => (
              <tr key={`${entry.kind}-${entry.id}`}>
                <td data-label="When">{entry.at ? formatDateTime(entry.at) : "–"}</td>
                <td data-label="What">{entry.kind === "backup" ? "Backup" : "Restore"}</td>
                <td data-label="Workspace">{entry.workspace || "–"}</td>
                <td data-label="Who">{entry.by || "–"}</td>
                <td data-label="Result">{entry.result}</td>
                <td>
                  {entry.downloadable ? (
                    <a className="admin-panel__action-btn" href={`${DATA}/exports/${encodeURIComponent(entry.id)}/download`}>Download</a>
                  ) : null}
                </td>
              </tr>
            ))}
      </tbody>
    </table>
  </section>
  );
}
