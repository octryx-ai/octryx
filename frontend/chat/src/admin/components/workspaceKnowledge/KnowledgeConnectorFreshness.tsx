import type { SourceConnector } from "./connectorTypes";
import { isLocalSnapshot } from "./gitRepositoryScope";
import {
  instanceSchedulerText,
  lastFullPassText,
  nextRunText,
  pageCountsText,
  runModeText,
  runPageCounts,
  withheldText,
} from "./connectorFreshness";
import type { InstanceScheduler } from "./connectorFreshness";

// How fresh one connector's knowledge is: how the last run listed the source and what it changed, the
// last clean full pass, the next scheduled run, whether this instance runs schedules at all (when the server says),
// and why restricted items are missing. What a full pass does is page help (help/knowledge/workspaceKnowledge.md). Read-only. The run's state badge and times stay in the table and the last-run section
// (not repeated here).
export function KnowledgeConnectorFreshness({
  connector,
  instance,
}: {
  connector: SourceConnector;
  instance: InstanceScheduler;
}) {
  const run = connector.last_run;
  const counts = runPageCounts(run?.report);
  const withheld = withheldText(connector.kind, run?.report);
  const mode = runModeText(connector.kind, run?.report);
  return (
    // A tab of the source's side panel, whose title names the source: no heading, no extra indent.
    <div data-testid="connector-freshness">
      <dl
        className="admin-panel__stack admin-panel__stack--compact"
        style={{ margin: 0 }}
      >
        <div>
          <dt className="admin-panel__muted">Last run</dt>
          <dd style={{ margin: 0 }} data-testid="freshness-last-run">
            {run ? (
              <>
                {mode ? <span data-testid="freshness-mode">{mode} · </span> : null}
                <span>{pageCountsText(connector.kind, counts)}</span>
              </>
            ) : isLocalSnapshot(connector) ? (
              "Uploaded by the launcher; no sync runs."
            ) : (
              "Not run yet."
            )}
            {connector.running ? (
              <span className="admin-panel__muted"> A run is in progress.</span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="admin-panel__muted">Last full pass</dt>
          <dd style={{ margin: 0 }} data-testid="freshness-full-pass">
            {lastFullPassText(connector.kind, connector.cursor)}
          </dd>
        </div>
        <div>
          <dt className="admin-panel__muted">Next run</dt>
          <dd style={{ margin: 0 }} data-testid="freshness-next-run">
            {nextRunText(connector, instance)}
          </dd>
        </div>
        {instance !== "unknown" ? <div>
          <dt className="admin-panel__muted">
            Scheduled runs on this instance
          </dt>
          <dd
            style={{ margin: 0 }}
            data-testid="freshness-instance"
            data-instance={instance}
          >
            {instanceSchedulerText(instance)}
          </dd>
        </div> : null}
      </dl>
      {withheld ? (
        <div
          className="admin-panel__hint"
          role="note"
          data-testid="freshness-withheld"
          style={{ margin: "0.5rem 0 0" }}
        >
          {withheld}
        </div>
      ) : null}
    </div>
  );
}
