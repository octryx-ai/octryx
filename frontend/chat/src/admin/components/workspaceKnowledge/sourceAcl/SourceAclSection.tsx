import { useCallback, useEffect, useState } from "react";
import { SidePanel } from "../../../../layout/SidePanel";
import { StatusLabel } from "../../../../layout/StatusLabel";
import { FormSection } from "../../../../layout/FormSection";
import { useConfirmAction } from "../../confirm/useConfirmAction";
import { requestedSourceAcl } from "../sourceLinks";
import { sourceAclApi } from "./sourceAclApi";
import {
  SOURCE_ACL_TITLE, sourceAclDoneText, sourceAclOf, sourceAclPanelView, sourceAclPreviewOf, sourceAclPreviewText,
  sourceAclRefusal, sourceAclSummary,
} from "./sourceAclModel";
import type { SourceAcl, SourceAclPreview } from "./sourceAclModel";
import "./source-acl.css";

// Knowledge › Sources, below the list (platform admins only): whether this Workspace enforces source
// permissions and how many restricted items are held back. "Change" opens a panel with the required reason, a preview
// (dry run) of the change, and the change itself after an in-page confirmation. A link with ?source_acl=open (the
// held-back notice of a REST source) opens the panel directly.

const opened = () => {
  try { return requestedSourceAcl(typeof window === "undefined" ? "" : window.location?.search ?? ""); } catch { return false; }
};

export function SourceAclSection({ workspaceId }: { workspaceId: string }) {
  const [acl, setAcl] = useState<SourceAcl | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState(opened);
  const confirmAction = useConfirmAction();

  const load = useCallback(async () => {
    try {
      const state = sourceAclOf(await sourceAclApi.get(workspaceId));
      setAcl(state);
      setProblem(state ? null : "The server's answer could not be read. Reload the page.");
    } catch (error) {
      setProblem(sourceAclRefusal(error));
    }
  }, [workspaceId]);
  useEffect(() => { void load(); }, [load]);

  const summary = acl ? sourceAclSummary(acl) : null;
  return (
    <section className="admin-panel__card source-acl" aria-label="Source permissions" data-testid="source-acl">
      <div className="source-acl__head">
        <div className="source-acl__title">
          <span>{SOURCE_ACL_TITLE}</span>
          {summary ? <StatusLabel label={summary.label} tone="neutral" testId="source-acl-state" /> : null}
        </div>
        {acl ? (
          <button type="button" className="admin-panel__action-btn" onClick={() => setOpen(true)} data-testid="source-acl-change">
            Change
          </button>
        ) : null}
      </div>
      {summary ? (
        <div className="source-acl__lines">
          <p data-testid="source-acl-held-back">{summary.heldBack}</p>
          {summary.note ? <p className="admin-panel__muted">{summary.note}</p> : null}
        </div>
      ) : problem ? null : <p className="admin-panel__muted">Reading…</p>}
      {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
      {confirmAction.notice}
      {confirmAction.dialog}
      {open && acl ? (
        <SourceAclPanel workspaceId={workspaceId} acl={acl} onClose={() => setOpen(false)}
          onConfirm={(target, reason, previewText) => confirmAction.ask({
            title: `${target ? "Turn on" : "Turn off"} source permissions for this Workspace?`,
            body: <><p>{previewText}</p><p>The change is recorded in the audit log with your reason.</p></>,
            confirmLabel: target ? "Turn on" : "Turn off",
            tone: "neutral",
            run: async () => {
              try {
                await sourceAclApi.put(workspaceId, target, reason, false);
              } catch (error) {
                throw new Error(sourceAclRefusal(error));
              }
              setOpen(false);
              await load();
            },
            done: sourceAclDoneText(target),
          })} />
      ) : null}
    </section>
  );
}

function SourceAclPanel({ workspaceId, acl, onClose, onConfirm }: {
  workspaceId: string;
  acl: SourceAcl;
  onClose: () => void;
  onConfirm: (target: boolean, reason: string, previewText: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<SourceAclPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = sourceAclPanelView({ acl, reason, preview, busy });
  const summary = sourceAclSummary(acl);

  async function runPreview() {
    setBusy(true);
    setError(null);
    try {
      const answer = sourceAclPreviewOf(await sourceAclApi.put(workspaceId, view.target, reason, true));
      setPreview(answer);
      if (!answer) setError("The server's answer could not be read. Try again.");
    } catch (failure) {
      setPreview(null);
      setError(sourceAclRefusal(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SidePanel title="Source permissions" onClose={onClose} testId="source-acl-panel" size="narrow"
      footer={<>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={!view.confirmEnabled}
          title={view.waiting ?? undefined} data-testid="source-acl-confirm"
          onClick={() => preview && onConfirm(view.target, reason, sourceAclPreviewText(preview))}>{view.actionLabel}</button>
      </>}>
      <FormSection title={SOURCE_ACL_TITLE}>
        <div className="source-acl__title"><span>Now</span><StatusLabel label={summary.label} tone="neutral" /></div>
        <p className="source-acl__text">{summary.heldBack}</p>
        {summary.note ? <p className="source-acl__text admin-panel__muted">{summary.note}</p> : null}
        <p className="source-acl__text admin-panel__muted">
          On, items restricted by grant are indexed and found only by the members their source admits. Off, they are held
          back, and a restricted source syncs nothing people can find.
        </p>
      </FormSection>
      <FormSection title={`${view.actionLabel} for this Workspace`}>
        <label className="admin-panel__field">
          <span>Reason (required)</span>
          <textarea className="admin-panel__input" rows={3} value={reason} data-testid="source-acl-reason"
            placeholder="Why this Workspace changes it, for the audit log"
            onChange={(event) => { setReason(event.target.value); setError(null); }} />
        </label>
        <div>
          <button type="button" className="admin-panel__action-btn" disabled={!view.previewEnabled}
            onClick={() => void runPreview()} data-testid="source-acl-preview">{busy ? "Checking…" : "Preview"}</button>
        </div>
        {view.previewText ? (
          <p className="source-acl__preview" role="status" data-testid="source-acl-preview-result">{view.previewText}</p>
        ) : null}
        {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
        {view.waiting ? <p className="admin-panel__muted source-acl__text">{view.waiting}</p> : null}
      </FormSection>
    </SidePanel>
  );
}
