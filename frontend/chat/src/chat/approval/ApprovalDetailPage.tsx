import { useCallback, useEffect, useState } from "react";

import "./approvalDetail.css";
import { AdminDetailFacts } from "../../admin/components/AdminDetailFacts";
import { StatusLabel } from "../../layout/StatusLabel";
import { approvalDecisionErrorText, type ApprovalDecisionKind } from "../approvalCardActions";
import { responseDetailCode, responseDetailText } from "../chatApiClient";
import { formatChatShortDateTime } from "../chatTimestamp";
import { RedactedText } from "../redaction/RedactedText";
import { ApprovalPreview } from "./ApprovalPreview";
import { ConnectorWriteFields } from "./ConnectorWriteCard";
import { RestRequestPreview } from "./RestRequestPreview";
import { WriteList, WritePlanScope } from "./WritePlanCard";
import {
  approvalDecisionRequest,
  approvalDetailActions,
  approvalDetailLinks,
  approvalDetailNote,
  approvalDetailState,
  approvalDetailStatus,
  approvalIdFromSearch,
  approvalTexts,
  approvalPreviewKind,
  personText,
  type ApprovalDetail,
  type ApprovalDetailState,
} from "./approvalDetailModel";
import { connectorWriteView } from "./connectorWriteView";
import { restRequestView } from "./restRequestView";
import { writePlanView } from "./writePlanView";

type Project = { id: string; name: string };

async function fetchJson(url: string, init?: RequestInit): Promise<{ status: number; payload: unknown }> {
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
      ...init,
    });
    return { status: response.status, payload: await response.json().catch(() => null) };
  } catch {
    return { status: 0, payload: null };
  }
}

const when = (value: string | null) => formatChatShortDateTime(value, "");

// Operations › Decisions › Approval: one approval as the server stored it (backend). Status, who asked and who
// decided, the Workspace and the chat or run it belongs to, the masked preview, and while it waits the decisions the
// server offers. Out of reach or unknown is one sentence.
export function ApprovalDetailPage({ projects }: { projects: Project[] }) {
  const [approvalId] = useState(() => approvalIdFromSearch(typeof window === "undefined" ? "" : window.location.search));
  const [state, setState] = useState<ApprovalDetailState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!approvalId) {
      setState({ kind: "message", text: "No approval is named in the address." });
      return;
    }
    setState(approvalDetailState(await fetchJson(`/api/v1/approvals/${encodeURIComponent(approvalId)}`)));
  }, [approvalId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") return <p className="ob-muted" data-testid="approval-detail-loading">Loading the approval…</p>;
  if (state.kind === "message") {
    return <p className="approval-detail__message" role="status" data-testid="approval-detail-message">{state.text}</p>;
  }

  const decide = async (detail: ApprovalDetail, decision: ApprovalDecisionKind) => {
    setBusy(true);
    setError(null);
    const request = approvalDecisionRequest(detail, decision);
    const answer = await fetchJson(request.url, { method: "POST", ...(request.body ? { body: request.body } : {}) });
    if (answer.status < 200 || answer.status >= 300) {
      const refusal = (answer.payload as { detail?: unknown } | null)?.detail;
      setError(approvalDecisionErrorText(decision, answer.status || null, responseDetailText(refusal), responseDetailCode(refusal)));
    }
    await load();
    setBusy(false);
  };

  return <ApprovalDetailView detail={state.detail} projects={projects} busy={busy} error={error} onDecide={decide} />;
}

export function ApprovalDetailView({ detail, projects, busy, error, onDecide }: {
  detail: ApprovalDetail;
  projects: Project[];
  busy: boolean;
  error: string | null;
  onDecide: (detail: ApprovalDetail, decision: ApprovalDecisionKind) => void;
}) {
  const status = approvalDetailStatus(detail.status);
  const kind = approvalPreviewKind(detail.payload);
  const actions = approvalDetailActions(detail, kind);
  const workspace = detail.workspaceId ? projects.find((project) => project.id === detail.workspaceId)?.name ?? detail.workspaceId : "";
  const decided = detail.status !== "pending" && (detail.approvedBy || detail.approvedByName)
    ? `${status.label} by ${personText(detail.approvedByName, detail.approvedBy)}${detail.resolvedAt ? ` · ${when(detail.resolvedAt)}` : ""}`
    : detail.status === "expired" && detail.resolvedAt ? `Timed out · ${when(detail.resolvedAt)}` : "";
  const links = approvalDetailLinks(detail);
  const texts = approvalTexts(detail, detail.payload);
  return (
    <article className="approval-detail" data-testid="approval-detail" data-status={detail.status}>
      <header className="approval-detail__head">
        <div className="approval-detail__heading">
          <h2 className="approval-detail__title"><RedactedText value={texts.title} /></h2>
          {texts.subtitle ? (
            <p className="approval-detail__subtitle" data-testid="approval-detail-subtitle"><RedactedText value={texts.subtitle} /></p>
          ) : null}
        </div>
        <StatusLabel label={status.label} tone={status.tone} testId="approval-detail-status" />
      </header>
      <AdminDetailFacts testId="approval-detail-facts" facts={[
        { label: "Requested", value: `${personText(detail.requestedByName, detail.requestedBy)}${detail.createdAt ? ` · ${when(detail.createdAt)}` : ""}` },
        { label: "Decided", value: decided },
        { label: "Note", value: detail.decisionNote ? <RedactedText value={detail.decisionNote} /> : "" },
        { label: "Workspace", value: workspace },
        ...links.map((link) => ({ label: link.label, value: <a className="ds-link-button" href={link.href} data-testid="approval-detail-link">{link.text}</a> })),
        { label: "Approval", value: <span className="approval-detail__id" title={detail.id}>{detail.id}</span> },
      ]} />
      {actions.length ? (
        <section className="approval-detail__decide" aria-label="Decide" data-testid="approval-detail-decide">
          <span className="approval-detail__note">{approvalDetailNote(actions, kind)}</span>
          <div className="approval-detail__actions">
            {actions.map((action) => (
              <button key={action.kind} type="button" disabled={busy} data-testid={`approval-detail-${action.kind}`}
                className={action.kind === "approve" ? "ds-btn ds-btn--primary" : "ds-btn"}
                onClick={() => onDecide(detail, action.kind)}>
                {action.label}
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {error ? <p className="approval-detail__error" role="alert" data-testid="approval-detail-error">{error}</p> : null}
      <section className="approval-detail__section" aria-label="What was asked">
        <h3 className="approval-detail__section-title">What was asked</h3>
        <ApprovalDetailPreview detail={detail} kind={kind} />
      </section>
    </article>
  );
}

function ApprovalDetailPreview({ detail, kind }: { detail: ApprovalDetail; kind: ReturnType<typeof approvalPreviewKind> }) {
  const payload = detail.payload;
  if (kind === "plan") {
    const plan = writePlanView(payload);
    return plan ? (
      <div className="write-plan approval-detail__plan">
        {plan.request ? <p className="write-plan__request"><RedactedText value={plan.request} /></p> : null}
        <WritePlanScope groups={plan.scope} />
        <WriteList writes={plan.writes} startOpen={!plan.many} />
      </div>
    ) : null;
  }
  if (kind === "rest") {
    const view = restRequestView(payload);
    return view ? <RestRequestPreview view={view} /> : null;
  }
  if (kind === "connector") {
    const view = connectorWriteView(payload, typeof payload?.toolName === "string" ? payload.toolName : null);
    return view ? <ConnectorWriteFields view={view} /> : null;
  }
  if (kind === "generic") return <ApprovalPreview preview={{ id: "", preview: payload }} details={detail.details} />;
  return (
    <p className="ob-muted">
      {detail.action ? <RedactedText value={detail.action} /> : "No preview was stored for this approval."}
    </p>
  );
}
