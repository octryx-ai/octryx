// The inline approval card's action buttons and its folded details (the governed change and the reason).
import type { ApprovalSummary } from "../chatDecisionTypes";
import type {
  ApprovalCardAction,
  ApprovalCardModel,
  ApprovalDecisionKind,
} from "./approvalCardActions";
import type { ApprovalInlineView } from "./approvalInlineView";
import { ApprovalPreview } from "./approval/ApprovalPreview";
import { RedactedText } from "./redaction/RedactedText";

type DecisionHandler = (approval: ApprovalSummary, decision: ApprovalDecisionKind) => void;

type ActionButtonProps = {
  approval: ApprovalSummary;
  standingScope: string | null;
  onDecision: DecisionHandler;
  actionsDisabled: boolean;
  retrying: boolean;
  onRetry: () => void;
};

// One decision button; a retry reruns the request instead of sending a decision.
function ApprovalActionButton({
  action, approval, standingScope, onDecision, actionsDisabled, retrying, onRetry,
}: ActionButtonProps & { action: ApprovalCardAction }) {
  const kind = action.kind;
  const decision: ApprovalDecisionKind = kind === "reject" || kind === "always" ? kind : "approve";
  return (
    <button
      type="button"
      className={kind === "reject" ? "plain-button plain-button--danger approval-card__button approval-card__button--reject"
        : kind === "approve" ? "solid-button approval-card__button approval-card__button--approve"
        : `plain-button approval-card__button approval-card__button--${kind}`}
      disabled={kind === "retry" ? actionsDisabled || retrying : actionsDisabled}
      title={kind === "always" ? standingScope ?? undefined : undefined}
      onClick={kind === "retry" ? onRetry : () => onDecision(approval, decision)}
    >
      {kind === "retry" && retrying ? "Rerunning…" : action.label}
    </button>
  );
}

export function ApprovalInlineActions({
  card,
  approvalStatus,
  ...buttonProps
}: ActionButtonProps & { card: ApprovalCardModel; approvalStatus: string }) {
  return (
    <div className="approval-inline__actions">
      {card.actions.map((action) => (
        <ApprovalActionButton key={action.kind} action={action} {...buttonProps} />
      ))}
      {card.statusLabel ? (
        <span
          className={`approval-card__status approval-card__status--${approvalStatus}`}
        >
          {card.statusLabel}
        </span>
      ) : null}
    </div>
  );
}

function ApprovalPreviewShell({ approval, view }: { approval: ApprovalSummary; view: ApprovalInlineView }) {
  const { previewSummary, previewCommand, previewCwd, previewPath } = view;
  return (
    <div className="approval-card__preview-shell">
      {approval.action ? (
        <div className="approval-card__preview-summary">
          <RedactedText value={approval.action} />
        </div>
      ) : null}
      {previewSummary ? (
        <div className="approval-card__preview-summary approval-card__preview-summary--muted">
          <RedactedText value={previewSummary} />
        </div>
      ) : null}
      {previewCommand ? (
        <pre className="approval-preview__code"><RedactedText value={previewCommand} /></pre>
      ) : null}
      {previewCwd || previewPath ? (
        <div className="approval-preview__meta">
          {previewCwd ? <span>cwd: {previewCwd}</span> : null}
          {previewPath ? <span>path: {previewPath}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

export function ApprovalInlineDetails({
  approval,
  view,
  onRetryFromChangePreview,
  retryPrompt,
  actionsDisabled,
}: {
  approval: ApprovalSummary;
  view: ApprovalInlineView;
  onRetryFromChangePreview?: (previewId: string, prompt: string) => Promise<void>;
  retryPrompt?: string | null;
  actionsDisabled: boolean;
}) {
  return (
    <div className="approval-inline__details-stack">
      {approval.changePreview ? (
        <details className="approval-card__preview" open={view.isRestRequest || undefined}>
          <summary className="approval-card__preview-toggle">
            <span>Inspect governed change</span>
          </summary>
          {/* A REST write's own preview names the request; the raw action line would only repeat it. */}
          {view.isRestRequest ? null : <ApprovalPreviewShell approval={approval} view={view} />}
          <ApprovalPreview
            preview={approval.changePreview}
            details={approval.details}
            onRetryFromPreview={onRetryFromChangePreview}
            retryPrompt={retryPrompt}
            actionsDisabled={actionsDisabled}
          />
        </details>
      ) : null}
      {approval.reason ? (
        <details className="approval-card__details">
          <summary className="approval-card__details-toggle">
            Why this needs approval
          </summary>
          <pre className="approval-card__reason"><RedactedText value={view.reasonMeta.raw} /></pre>
        </details>
      ) : null}
    </div>
  );
}
