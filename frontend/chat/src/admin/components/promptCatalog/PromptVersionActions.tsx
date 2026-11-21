import { useState } from "react";
import { approvalDetailHref } from "../../../chat/approval/approvalDetailModel";
import { useApprovalRule } from "../approvalRule/approvalRule";
import type { PromptDetailModel } from "./usePromptCatalog";
import type { PromptVersion } from "./promptCatalogTypes";

type Props = { model: PromptDetailModel; version: PromptVersion; currentUserId?: string };

// The governed lifecycle of one version (the same for every key): a draft is submitted for four-eyes
// review and published with the approved approval; retire asks first. When the approval rule allows
// self-approval, a version publishes in one step instead. Only actions the server would accept for the
// version's state are offered.
export function PromptVersionActions({ model, version, currentUserId = "" }: Props) {
  // Typed by hand only when the server has not linked one yet; after a submit the version carries its approval.
  const [typedApprovalId, setApprovalId] = useState("");
  const approvalId = typedApprovalId || version.approval_id || "";
  const [confirmRetire, setConfirmRetire] = useState(false);
  const selfApprove = useApprovalRule().selfApprovalAllowed;
  const busy = model.busy !== null;
  const { state } = version;
  const selfPublish = selfApprove && (state === "draft" || state === "in_review");

  return (
    <div className="pc-actions">
      <VersionButtons model={model} version={version} busy={busy} selfApprove={selfApprove} selfPublish={selfPublish}
        onRetire={() => setConfirmRetire(true)} />
      {selfPublish ? (
        <span className="ws-muted">The approval rule lets you approve and publish your own change in one step.</span>
      ) : null}
      {state === "in_review" && !selfApprove ? (
        <InReviewApproval model={model} version={version} currentUserId={currentUserId} busy={busy} approvalId={approvalId}
          onApprovalId={setApprovalId} />
      ) : null}
      {confirmRetire ? (
        <RetireConfirm model={model} version={version} busy={busy} onClose={() => setConfirmRetire(false)} />
      ) : null}
    </div>
  );
}

type PartProps = { model: PromptDetailModel; version: PromptVersion; busy: boolean };

// Diff, the one-step or four-eyes publish path the rule allows, and Retire (which asks first).
function VersionButtons({ model, version, busy, selfApprove, selfPublish, onRetire }: PartProps & {
  selfApprove: boolean;
  selfPublish: boolean;
  onRetire: () => void;
}) {
  const { state } = version;
  return (
    <div className="pc-row">
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void model.showDiff(version.id)}>
        {model.busy === "diff" ? "Loading diff…" : "Diff"}
      </button>
      {selfPublish ? (
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy}
          onClick={() => void model.publishSelfApproved(version.id, state)}
        >
          {model.busy === "publish" ? "Publishing…" : "Publish"}
        </button>
      ) : null}
      {state === "draft" && !selfApprove ? (
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy}
          onClick={() => void model.submit(version.id)}
        >
          {model.busy === "submit" ? "Submitting…" : "Submit for four-eyes review"}
        </button>
      ) : null}
      {state !== "retired" ? (
        <button type="button" className="admin-panel__danger-btn" disabled={busy} onClick={onRetire}>
          Retire v{version.version}
        </button>
      ) : null}
    </div>
  );
}

// A version in four-eyes review: the second person decides here; anyone may publish with the approved approval.
function InReviewApproval({ model, version, currentUserId, busy, approvalId, onApprovalId }: PartProps & {
  currentUserId: string;
  approvalId: string;
  onApprovalId: (value: string) => void;
}) {
  return (
    <div className="pc-approval">
      <span className="ws-muted">
        {version.created_by === currentUserId
          ? "In review: another person who may change this scope approves it. Then publish it."
          : "In review: approve or reject this change. After approval, publish it."}
      </span>
      {version.approval_id && version.created_by !== currentUserId ? (
        // The second person decides right here, like a skill review; the server checks who may approve.
        <div className="pc-row" data-testid="pc-review-decide">
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={() => void model.approve(version.approval_id!)}>
            {model.busy === "decide" ? "Saving…" : "Approve"}
          </button>
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={() => void model.reject(version.approval_id!)}>
            Reject
          </button>
        </div>
      ) : null}
      {version.approval_id ? (
        <a className="pc-review-link" href={approvalDetailHref(version.approval_id)} data-testid="pc-open-review">
          Review details
        </a>
      ) : null}
      <div className="pc-row">
        <input
          className="admin-panel__form-input"
          aria-label="Approval id"
          placeholder="Approval id"
          value={approvalId}
          onChange={(event) => onApprovalId(event.target.value)}
        />
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy || !approvalId.trim()}
          onClick={() => void model.publish(version.id, approvalId.trim())}
        >
          {model.busy === "publish" ? "Publishing…" : "Publish with approval"}
        </button>
      </div>
    </div>
  );
}

function RetireConfirm({ model, version, busy, onClose }: PartProps & { onClose: () => void }) {
  return (
    <div className="ws-alert ws-alert--error" role="alertdialog" aria-label="Confirm retirement">
      <span>
        {version.state === "published"
          ? `Retire the published v${version.version}? The next turn falls back to the next broader text (workflow, global or shipped).`
          : `Retire v${version.version}? It can no longer be published.`}
      </span>
      <div className="pc-row pc-row--end">
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="admin-panel__danger-btn"
          disabled={busy}
          onClick={async () => {
            if (await model.retire(version.id)) onClose();
          }}
        >
          Retire v{version.version}
        </button>
      </div>
    </div>
  );
}
