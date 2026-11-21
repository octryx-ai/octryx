import { useState } from "react";
import { ACCESS_MODE_LABEL } from "../connectorTypes";
import { accessModeOf, repositoryConnectionOf, takesGitToken } from "../connectorConfig";
import { connectorsApi } from "../connectorsApi";
import type { AccessMode, SourceConnector, SyncRun } from "../connectorTypes";
import type { InstanceScheduler } from "../connectorFreshness";
import { KnowledgeConnectorFreshness } from "../KnowledgeConnectorFreshness";
import { KnowledgeConnectorRun } from "../KnowledgeConnectorRun";
import { isLocalSnapshot } from "../gitRepositoryScope";
import { TimeText } from "../../../utils/TimeText";
import { SidePanel } from "../../../../layout/SidePanel";
import { StatusLabel } from "../../../../layout/StatusLabel";
import { SourceGitToken } from "./SourceGitToken";
import { SourceSetupDetails } from "./SourceSetupDetails";
import { RestSourceStatus } from "../rest/RestSourceStatus";
import { REST_KIND } from "../rest/restSourceForm";
import { sourcePageHref } from "./sourceRowModel";
import {
  servedItemsText, sourceCadence, sourceContainer, sourceName, sourceOriginLabel, sourceState,
} from "./sourceState";

export type SourceDetailTab = "overview" | "setup" | "runs" | "freshness";

const ACCESS_MODES: AccessMode[] = ["read_only", "read_write"];

// A Git repository read through a connection: its access mode, which an author changes here (read & write lets agents
// push, branch and open pull requests on it through the connection).
function SourceAccessMode({ connector, workspaceId, editable, onChanged }: {
  connector: SourceConnector; workspaceId: string; editable: boolean; onChanged?: (connector: SourceConnector) => void;
}) {
  const current = accessModeOf(connector) ?? "read_only";
  const [chosen, setChosen] = useState<AccessMode>(current);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!editable) return <span data-testid="source-access-mode">{ACCESS_MODE_LABEL[current]}</span>;
  const save = async () => {
    setSaving(true);
    setProblem(null);
    try {
      const described = await connectorsApi.setAccessMode(workspaceId, connector.connector_key, chosen);
      onChanged?.(described);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="admin-panel__stack admin-panel__stack--compact">
      <div className="admin-users__row-actions" style={{ alignItems: "center" }}>
        <select className="admin-panel__input" style={{ width: "auto" }} aria-label="Access mode" value={chosen}
          disabled={saving} data-testid="source-access-mode" onChange={(event) => setChosen(event.target.value as AccessMode)}>
          {ACCESS_MODES.map((mode) => <option key={mode} value={mode}>{ACCESS_MODE_LABEL[mode]}</option>)}
        </select>
        {chosen !== current ? (
          <button type="button" className="admin-panel__action-btn" disabled={saving} data-testid="source-access-mode-save"
            onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
        ) : null}
      </div>
      {chosen === "read_write" ? (
        <span className="admin-panel__muted">Agents may push, create branches and open pull requests on it through the connection.</span>
      ) : null}
      {problem ? <span className="admin-panel__hint" role="alert" style={{ margin: 0 }}>{problem}</span> : null}
    </div>
  );
}

const TABS: { key: SourceDetailTab; label: string }[] = [
  { key: "overview", label: "Overview" }, { key: "setup", label: "Setup" }, { key: "runs", label: "Runs" },
  { key: "freshness", label: "Freshness" },
];

// One source in the design system's side panel (Knowledge › Sources): Overview, Setup, Runs and Freshness hold the
// source's details. Sync now and Edit sit in the footer; Remove stays in the row
// menu with its confirmation. mode="page" is the same content as a page ("Open as page").
export function SourceDetailPanel({
  connector, workspaceId, lastRun, running, busy, mayAuthor, schedulingOn, instance, onClose, onRun, onEdit, mode = "panel",
  onAccessModeChanged, isPlatformAdmin = false,
}: {
  connector: SourceConnector; workspaceId: string; lastRun: SyncRun | null; running: boolean; busy: boolean; mayAuthor: boolean;
  schedulingOn: boolean; instance: InstanceScheduler; onClose: () => void; onRun: () => void; onEdit: () => void;
  mode?: "panel" | "page";
  // A Git repository read through a connection: its access mode or its own Git token was changed (the described
  // connector).
  onAccessModeChanged?: (connector: SourceConnector) => void;
  // Presentation only: a platform admin's held-back notice links to the source-permissions switch.
  isPlatformAdmin?: boolean;
}) {
  const [tab, setTab] = useState<SourceDetailTab>("overview");
  const name = sourceName(connector);
  const state = sourceState(connector, running, schedulingOn);
  const snapshot = isLocalSnapshot(connector);
  const paused = connector.state === "paused";
  const syncing = connector.running || running;
  const items = servedItemsText(connector);
  const connection = repositoryConnectionOf(connector);
  const footer = mayAuthor && !snapshot ? (
    <>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onEdit}>Edit</button>
      <button type="button" className="admin-panel__action-btn" disabled={busy || paused || syncing} onClick={onRun}
        title={paused ? "Resume the source to sync it" : undefined} data-testid="source-sync-now">
        {syncing ? "Syncing…" : "Sync now"}
      </button>
    </>
  ) : undefined;
  return (
    <SidePanel title={name} subtitle={[sourceOriginLabel(connector.kind), sourceContainer(connector)].filter(Boolean).join(" · ")}
      onClose={onClose} mode={mode} pageHref={sourcePageHref(workspaceId, connector.connector_key)} footer={footer}
      testId="source-panel"
      tabs={{ tabs: TABS, value: tab, onChange: (key) => setTab(key as SourceDetailTab), label: `Details of ${name}`, idPrefix: "source-detail" }}>
      {tab === "overview" ? (
        <dl className="knowledge-source__overview" data-testid="source-overview">
          <div><dt>State</dt><dd><StatusLabel label={state.word} tone={state.tone === "warning" ? "attention" : state.word === "Syncing" ? "info" : "neutral"} /></dd></div>
          {state.reason ? <div><dt>Why</dt><dd data-testid="knowledge-source-reason">{state.reason}</dd></div> : null}
          <div><dt>Last sync</dt><dd>{state.lastSyncAt === null ? "Not synced yet" : <TimeText value={state.lastSyncAt} />} · {sourceCadence(connector)}</dd></div>
          {items ? <div><dt>Items</dt><dd>{items}</dd></div> : null}
          {connection ? (
            <div>
              <dt>Access</dt>
              <dd>
                <SourceAccessMode key={`${connector.connector_key}:${accessModeOf(connector) ?? ""}`} connector={connector}
                  workspaceId={workspaceId} editable={mayAuthor && !snapshot} onChanged={onAccessModeChanged} />
                <div className="admin-panel__muted">Through the connection <code>{connection}</code></div>
              </dd>
            </div>
          ) : null}
          {takesGitToken(connector) ? (
            <div>
              <dt>Git token</dt>
              <dd>
                <SourceGitToken key={`${connector.connector_key}:${connector.git_token?.set_at ?? ""}`} connector={connector}
                  workspaceId={workspaceId} editable={mayAuthor && !snapshot} onChanged={onAccessModeChanged} />
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {tab === "overview" && connector.kind === REST_KIND ? <RestSourceStatus connector={connector} workspaceId={workspaceId} isPlatformAdmin={isPlatformAdmin} /> : null}
      {tab === "setup" ? <SourceSetupDetails connector={connector} name={name} /> : null}
      {tab === "runs" ? <KnowledgeConnectorRun connectorKey={name} run={lastRun} kind={connector.kind} snapshot={snapshot} /> : null}
      {tab === "freshness" ? <KnowledgeConnectorFreshness connector={connector} instance={instance} /> : null}
    </SidePanel>
  );
}
