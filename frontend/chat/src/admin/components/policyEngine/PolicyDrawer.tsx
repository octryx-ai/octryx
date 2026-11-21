import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { CedarCode } from "./CedarCode";
import { PolicySentence } from "./PolicySentence";
import { loadPolicy, loadPolicyDenialCounts } from "./policyEngineApi";
import { STATE_LABELS, serverDate } from "./policyEngineStatus";
import type { TestReport } from "./policyEngineVersions";
import { SOURCE_LABELS, effectOf, policyStatus, readPolicyHistory } from "./policyCatalogModel";
import type { PolicyHistoryEntry, PolicyItem } from "./policyCatalogModel";
import type { MenuEntry } from "./PolicyList";
import { formatDateTime } from "../../utils/dateTime";


export type DrawerContext = {
  versionNumber: number | null;
  versionState: string | null;
  publishedVersion: number | null;
  testReport: TestReport | null;
  // Engine mode: in shadow mode a Cedar deny did not block anything, so the effect says "would have denied".
  engineMode?: string;
};

type PolicyDrawerProps = {
  item: PolicyItem;
  context: DrawerContext;
  actions: { primary: MenuEntry | null; secondary: MenuEntry[]; danger: MenuEntry | null };
  onShowDecisions: () => void;
  onEditSource: (() => void) | null;
  onClose: () => void;
  confirmRemove?: boolean;
  /** "What would it block?" for builder policies. */
  impact?: ReactNode;
  /** Named connections by name, with a link back to the connector cards. */
  connectionLabel?: (id: string) => string;
  onOpenConnectors?: (() => void) | null;
  /** What this draft policy would have blocked in live traffic (draft shadow). */
  draftTraffic?: ReactNode;
};

// One policy: the sentence, the details, its effect in the decision log, the saved test cases
// that reference it, its version history and its Cedar (read-only, collapsed). Generated baseline policies are
// shown read-only with where they are edited.
export function PolicyDrawer({ item, context, actions, onShowDecisions, onEditSource, onClose, confirmRemove = false, impact = null,
  connectionLabel = (id) => id, onOpenConnectors = null, draftTraffic = null }: PolicyDrawerProps) {
  const generated = item.change === null;
  const status = policyStatus(item, context.versionState);
  const [history, setHistory] = useState<PolicyHistoryEntry[] | null>(null);
  const [blocked, setBlocked] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const version = item.change === "removed" ? context.publishedVersion : context.versionNumber;
    if (!generated && version !== null) {
      void loadPolicy(version, item.id).then((raw) => { if (alive) setHistory(readPolicyHistory(raw)); }).catch(() => { if (alive) setHistory([]); });
    }
    if (!generated && item.change !== "new") {
      void loadPolicyDenialCounts()
        .then((raw) => {
          const denied = (raw as { denied?: Record<string, number> } | null)?.denied ?? {};
          if (alive) setBlocked(Number(denied[item.id] ?? 0));
        })
        .catch(() => { if (alive) setBlocked(null); });
    }
    return () => { alive = false; };
  }, [item.id, item.change, generated, context.versionNumber, context.publishedVersion]);

  const eyebrow = `Policy · ${SOURCE_LABELS[item.source] ?? item.source}`;
  const footer = <DrawerFooter generated={generated} actions={actions} onClose={onClose} onEditSource={onEditSource} />;

  return (
    <SettingsDrawer eyebrow={eyebrow} title={item.name} size="detail" onClose={onClose} footer={footer}>
      <div className="policies__row" data-testid="policy-drawer">
        <span className={`work-badge work-badge--${effectOf(item).tone}`}>{effectOf(item).label}</span>
        <span className={`work-badge work-badge--${status.tone}`}>{status.label}</span>
        <span className="admin-policy-inline-code">{item.id}</span>
      </div>
      {confirmRemove ? (
        <div className="policies__warn" data-testid="policy-drawer-confirm-remove">
          Remove this policy from the draft? It stops blocking once the draft is published, which goes through review
          like every change. Press <b>Confirm remove</b>.
        </div>
      ) : null}
      <section className="work-detail__section">
        <h3>In plain language</h3>
        <PolicySentence segments={item.sentence} testId="policy-drawer-sentence" />
        {item.description ? <p>{item.description}</p> : null}
        {item.warnings.map((warning) => <div key={`${warning.code}-${warning.id}`} className="policies__warn" data-testid="policy-drawer-warning">{warning.message}</div>)}
      </section>
      <DetailsSection item={item} generated={generated} connectionLabel={connectionLabel} onOpenConnectors={onOpenConnectors} />
      {!generated ? (
        <EffectSection item={item} blocked={blocked} engineMode={context.engineMode} testReport={context.testReport}
          draftTraffic={draftTraffic} onShowDecisions={onShowDecisions} />
      ) : null}
      {impact ? <section className="work-detail__section">{impact}</section> : null}
      {!generated ? <HistorySection history={history} /> : null}
      <details className="policies__advanced">
        <summary>Cedar</summary>
        <CedarCode text={item.text} testId="policy-drawer-cedar" />
      </details>
    </SettingsDrawer>
  );
}

function DrawerFooter({ generated, actions, onClose, onEditSource }: {
  generated: boolean;
  actions: { primary: MenuEntry | null; secondary: MenuEntry[]; danger: MenuEntry | null };
  onClose: () => void;
  onEditSource: (() => void) | null;
}) {
  return generated ? (
    <>
      <span className="policies__spacer" />
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      {onEditSource ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-edit-source" onClick={onEditSource}>Edit at the source</button> : null}
    </>
  ) : (
    <>
      {actions.danger ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="policy-drawer-remove" disabled={actions.danger.disabled} onClick={actions.danger.onSelect}>{actions.danger.label}</button> : null}
      <span className="policies__spacer" />
      {actions.secondary.map((entry) => (
        <button key={entry.label} type="button" className="admin-panel__action-btn" disabled={entry.disabled} onClick={entry.onSelect}>{entry.label}</button>
      ))}
      {actions.primary ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-drawer-edit" disabled={actions.primary.disabled} onClick={actions.primary.onSelect}>{actions.primary.label}</button> : null}
    </>
  );
}

function DetailsSection({ item, generated, connectionLabel, onOpenConnectors }: {
  item: PolicyItem;
  generated: boolean;
  connectionLabel: (id: string) => string;
  onOpenConnectors: (() => void) | null;
}) {
  return (
    <section className="work-detail__section">
      <h3>Details</h3>
      <div className="work-detail__kv-grid">
        <dl className="work-detail__kv"><dt>Scope</dt><dd>{item.scope}</dd></dl>
        <dl className="work-detail__kv"><dt>Enforced at</dt><dd>{item.points.join(", ") || "—"}</dd></dl>
        <dl className="work-detail__kv"><dt>Author</dt><dd>{item.lastChanged ? `${item.lastChanged.byName || item.lastChanged.by || "—"} · v${item.lastChanged.version}` : "—"}</dd></dl>
        {item.references.connections.length ? (
          <dl className="work-detail__kv" data-testid="policy-drawer-connections"><dt>Connections</dt>
            <dd>{item.references.connections.map(connectionLabel).join(", ")}
              {onOpenConnectors ? <> · <button type="button" className="policies__link" data-testid="policy-drawer-open-connectors" onClick={onOpenConnectors}>Open connectors</button></> : null}</dd></dl>
        ) : null}
        <dl className="work-detail__kv"><dt>Source</dt><dd>{generated ? `${SOURCE_LABELS[item.source] ?? item.source} (generated, read-only)` : item.source === "builder" ? "Builder (re-opens in the builder)" : "Hand-written Cedar — edit it in the Cedar editor"}</dd></dl>
      </div>
      {generated ? <p data-testid="policy-drawer-generated">Generated from the {SOURCE_LABELS[item.source] ?? item.source}. Read-only here{item.editWhere ? ` — edit it at ${item.editWhere}` : ""}.</p> : null}
    </section>
  );
}

function EffectSection({ item, blocked, engineMode, testReport, draftTraffic, onShowDecisions }: {
  item: PolicyItem;
  blocked: number | null;
  engineMode?: string;
  testReport: TestReport | null;
  draftTraffic: ReactNode;
  onShowDecisions: () => void;
}) {
  const cases = (testReport?.results ?? []).filter((result) => result.determining.includes(item.id));
  const failing = cases.filter((result) => !result.passed);
  return (
    <section className="work-detail__section">
      <h3>Effect</h3>
      <p data-testid="policy-drawer-effect">
        {item.change === "new" ? <>Not published yet — check <b>What would this block?</b> in the editor.</>
          : blocked === null ? "Decisions are loading…"
            : <>{engineMode === "enforce" ? "Denied" : "Would have denied"} <b>{blocked}</b> request{blocked === 1 ? "" : "s"} in the last 7 days. <button type="button" className="policies__link" data-testid="policy-drawer-decisions" onClick={onShowDecisions}>Show in Decisions</button></>}
      </p>
      {draftTraffic}
      <p data-testid="policy-drawer-cases">
        {cases.length ? <>Test cases: <b>{cases.length}</b> reference this policy · {failing.length ? <span className="policies__fail">{failing.length} fail</span> : "all pass"}.</> : "No saved test case references this policy yet."}
      </p>
    </section>
  );
}

function HistorySection({ history }: { history: PolicyHistoryEntry[] | null }) {
  return (
    <section className="work-detail__section">
      <h3>History</h3>
      {history === null ? <p>Loading…</p> : history.length ? (
        <ul className="policies__summary" data-testid="policy-drawer-history">
          {history.map((entry) => (
            <li key={entry.version}>v{entry.version} · {entry.change} · {STATE_LABELS[entry.state] ?? entry.state}{entry.byName ? ` · by ${entry.byName}` : ""}{entry.publishedAt ? ` · published ${formatDateTime(entry.publishedAt)}` : ""}</li>
          ))}
        </ul>
      ) : <p>No history yet.</p>}
    </section>
  );
}
