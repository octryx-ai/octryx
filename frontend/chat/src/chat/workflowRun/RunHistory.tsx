import { StatusLabel } from "../../layout/StatusLabel";
import { approvalDetailHref } from "../approval/approvalDetailModel";
import { OpenFindings } from "./OpenFindings";
import { RemedyAction } from "../devices/RemedyAction";
import type { RunHistoryEntry } from "./runHistoryModel";

// How this run went (run card mock): one line per step; a step the platform took on its own carries a
// quiet grey label and its reason, never a decision card.
// The run's open review findings (run view ``open_findings``) sit under the last "Open findings" line; without that
// line (events not loaded yet) they close the list.
export function RunHistory({ entries, openFindings }: { entries: RunHistoryEntry[]; openFindings?: unknown }) {
  const hasFindings = Array.isArray(openFindings) && openFindings.length > 0;
  if (!entries.length && !hasFindings) return null;
  const anchor = hasFindings ? entries.map((entry) => Boolean(entry.findings)).lastIndexOf(true) : -1;
  return (
    <section className="run-history" aria-label="How this run went" data-testid="workflow-run-history">
      <h4 className="run-history__title">How this run went</h4>
      <ol className="run-history__list">
        {entries.map((entry, index) => (
          <li key={entry.id} className="run-history__entry" data-auto={entry.auto ? "true" : undefined}
            data-quiet={entry.quiet ? "true" : undefined}>
            {entry.time ? <time className="run-history__time">{entry.time}</time> : null}
            {entry.link?.external && !entry.auto ? (
              <span>
                {`${entry.title}: `}
                <a href={entry.link.href} target="_blank" rel="noreferrer" data-testid="workflow-run-history-link">{entry.text}</a>
              </span>
            ) : (
              <span>{entry.auto || !entry.text ? entry.title : `${entry.title}: ${entry.text}`}</span>
            )}
            {entry.link && !entry.link.external ? (
              <a className="ds-link-button run-history__approval" href={entry.link.href} data-testid="workflow-run-history-link">
                {entry.link.label} ›
              </a>
            ) : null}
            {entry.approvalId ? (
              <a className="ds-link-button run-history__approval" href={approvalDetailHref(entry.approvalId)} data-testid="workflow-run-history-approval">
                Approval ›
              </a>
            ) : null}
            {entry.auto ? (
              <>
                <StatusLabel label={entry.auto} tone={entry.tone ?? "neutral"} testId="workflow-run-history-auto" />
                <span className="run-history__reason">{entry.text}</span>
                {entry.note ? <span className="run-history__note">{entry.note}</span> : null}
              </>
            ) : null}
            {entry.remedy ? <div className="run-history__remedy"><RemedyAction remedy={entry.remedy} /></div> : null}
            {index === anchor ? <OpenFindings value={openFindings} /> : null}
          </li>
        ))}
      </ol>
      {hasFindings && anchor < 0 ? <OpenFindings value={openFindings} /> : null}
    </section>
  );
}
