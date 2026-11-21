import { useEffect, useState } from "react";

import { approvalDetailHref } from "../../../chat/approval/approvalDetailModel";
import { useAdminNavigation } from "../../adminNavigation";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { Badge } from "./obUi";
import { formatTime, readErrorMessage } from "./obFormat";
import {
  decisionOutcomeLabel,
  decisionTone,
  EDIT_TARGETS,
  gateLabel,
  type DecisionDetail,
} from "./decisionsModel";

type Props = { decisionId: string; readJson: ReadJsonFn; onClose: () => void; onOpenRun: (runKey: string) => void };

// Decision drawer: outcome, gate, who and where, why (the reason given at the time is kept), the approval
// lifecycle, and links to the run and to the screen where the deciding rule is edited. Nothing is decided here.
export function DecisionDrawer({ decisionId, readJson, onClose, onOpenRun }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const [detail, setDetail] = useState<DecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    readJson<DecisionDetail>(`/api/v1/observability/decisions/${encodeURIComponent(decisionId)}`)
      .then((payload) => active && setDetail(payload))
      .catch((loadError) => active && setError(readErrorMessage(loadError, "The decision could not be loaded.")));
    return () => {
      active = false;
    };
  }, [decisionId, readJson]);

  const target = detail ? EDIT_TARGETS[detail.gate] : undefined;
  const editRule = () => {
    if (!target) return;
    if (target.tab) openAdminTab(target.tab);
    else if (target.href) window.location.assign(target.href);
  };
  const footer = <DecisionFooter detail={detail} target={target} onOpenRun={onOpenRun} editRule={editRule} />;

  return (
    <SettingsDrawer
      eyebrow={detail ? `Decision · ${formatTime(detail.time)} · ${gateLabel(detail.gate)}` : "Decision"}
      title={detail?.what || "Decision"}
      size="detail"
      onClose={onClose}
      footer={footer}
    >
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      {!detail && !error ? <span className="ob-muted">Loading the decision…</span> : null}
      {detail ? <DecisionBody detail={detail} target={target} /> : null}
    </SettingsDrawer>
  );
}

type EditTarget = (typeof EDIT_TARGETS)[string];

// Open approval, Open run (when the run still exists) and the link to where the deciding rule is edited.
function DecisionFooter({ detail, target, onOpenRun, editRule }: {
  detail: DecisionDetail | null; target: EditTarget | undefined; onOpenRun: (runKey: string) => void; editRule: () => void;
}) {
  return (
    <>
      {detail?.approval_id ? (
        <a className="admin-panel__action-btn" href={approvalDetailHref(detail.approval_id)} data-testid="decision-open-approval">
          Open approval
        </a>
      ) : null}
      <button type="button" className="admin-panel__action-btn" disabled={!detail?.run_exists}
        onClick={() => detail?.run_key && onOpenRun(detail.run_key)}>
        Open run
      </button>
      {target ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={editRule}>
          Edit rule in {target.label.split(" → ")[0]}
        </button>
      ) : null}
    </>
  );
}

// Outcome, gate, who and where, why, the approval lifecycle and the request's counts.
function DecisionBody({ detail, target }: { detail: DecisionDetail; target: EditTarget | undefined }) {
  return (
    <>
      <div className="ob-kv">
        <div><b>Outcome</b><Badge tone={decisionTone(detail.outcome)}>{decisionOutcomeLabel(detail.outcome)}</Badge></div>
        <div><b>Gate</b>{gateLabel(detail.gate)}</div>
        <div><b>Who · where</b>{detail.decided_by ?? detail.who} · {detail.workspace_name ?? "global"}</div>
        <div><b>Engine mode</b>{detail.mode}</div>
      </div>
      <section className="work-detail__section">
        <h3>Why</h3>
        {detail.subtitle ? <div>{detail.subtitle}</div> : null}
        <div>{detail.rule ?? "No rule recorded"}</div>
        {detail.rule_code ? <span className="ob-muted"><code>{detail.rule_code}</code></span> : null}
        {detail.reason ? <div>{detail.reason}</div> : null}
        <span className="ob-muted">The reason given at the time is kept; a later decision adds a record, it never overwrites this one.</span>
        {target ? <span className="ob-muted">Rules are edited in {target.label}.</span> : null}
      </section>
      {detail.lifecycle.length > 1 ? (
        <section className="work-detail__section">
          <h3>Approval lifecycle</h3>
          <div className="ob-steps">
            {detail.lifecycle.map((item) => (
              <div className="ob-step" key={item.id}>
                <span className="ob-mono">{formatTime(item.time)}</span>
                <span>{item.decided_by ? `by ${item.decided_by}` : `requested by ${item.who}`}{item.reason ? ` · ${item.reason}` : ""}</span>
                <Badge tone={decisionTone(item.outcome)}>{decisionOutcomeLabel(item.outcome)}</Badge>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      {detail.content || detail.obligation ? (
        <section className="work-detail__section">
          <h3>Request (counts only)</h3>
          <pre className="ob-diff">{JSON.stringify({ content: detail.content, obligation: detail.obligation }, null, 2)}</pre>
        </section>
      ) : null}
    </>
  );
}
