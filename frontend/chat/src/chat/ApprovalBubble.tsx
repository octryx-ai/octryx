import { useState } from "react";

import type { ApprovalSummary } from "../chatDecisionTypes";
import {
  approvalCardModel,
  standingRuleScopeLabel,
  type ApprovalDecisionKind,
} from "./approvalCardActions";
import { approvalEyebrow, readPreviewRecord } from "./approvalBubbleModel";
import { ApprovalInlineActions, ApprovalInlineDetails } from "./ApprovalInlineParts";
import { approvalInlineView, type ApprovalInlineView } from "./approvalInlineView";
import { approvalTexts } from "./approval/approvalDetailModel";
import { ConnectorWriteCard } from "./approval/ConnectorWriteCard";
import { connectorWriteView } from "./approval/connectorWriteView";
import { WritePlanCard } from "./approval/WritePlanCard";
import { RedactedText } from "./redaction/RedactedText";
import { writePlanView } from "./approval/writePlanView";

function ApprovalShieldIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 2.75 4 5.25v4.5c0 3.8 2.6 6.55 6 7 3.4-.45 6-3.2 6-7v-4.5l-6-2.5Z" />
      <path d="m7.6 10.15 1.55 1.55 3.2-3.2" />
    </svg>
  );
}

function ApprovalInlineBody({ title, view }: { title: string; view: ApprovalInlineView }) {
  const { metaLabel, reasonMeta, timestampLabel, shortFingerprint, whyLine } = view;
  return (
    <div className="approval-inline__body">
      <div className="approval-inline__eyebrow">
        {approvalEyebrow(view.approvalStatus)}
      </div>
      <div className="approval-inline__title" data-testid="approval-title">
        <RedactedText value={title} />
      </div>
      {whyLine ? (
        <div className="approval-inline__subtitle" data-testid="approval-subtitle"><RedactedText value={whyLine} /></div>
      ) : null}
      <div className="approval-inline__meta">
        {metaLabel ? <span>{metaLabel}</span> : null}
        {reasonMeta.analyzers ? (
          <span>policy: {reasonMeta.analyzers}</span>
        ) : null}
        {timestampLabel ? <span>{timestampLabel}</span> : null}
        {shortFingerprint ? <span>{shortFingerprint}</span> : null}
      </div>
    </div>
  );
}

type ApprovalBubbleProps = {
  approval: ApprovalSummary;
  onDecision: (approval: ApprovalSummary, decision: ApprovalDecisionKind) => void;
  onRetryFromApproval?: (approvalId: string, prompt: string) => Promise<void>;
  onRetryFromChangePreview?: (
    previewId: string,
    prompt: string,
  ) => Promise<void>;
  retryPrompt?: string | null;
  actionsDisabled?: boolean;
  // A Workspace admin or owner sees "Always for this Workspace".
  canGrantStandingConfirmation?: boolean;
  // The viewer, so a decided write plan says "by you" only to the person who decided it.
  currentUserId?: string | null;
};

export function ApprovalBubble(props: ApprovalBubbleProps) {
  const { approval, onDecision, actionsDisabled = false, currentUserId = null } = props;
  // The rerun's busy state lives here, above the card choice, so it survives a change of card type.
  const retry = useApprovalRetry(approval.id, props.onRetryFromApproval, props.retryPrompt, actionsDisabled);
  // A chat's write plan: one card for every write of the request, confirmed once.
  const planView = writePlanView(readPreviewRecord(approval.changePreview));
  if (planView) {
    return (
      <WritePlanCard
        approval={approval}
        view={planView}
        onDecision={onDecision}
        actionsDisabled={actionsDisabled}
        currentUserId={currentUserId}
      />
    );
  }
  // A chat's connector write has its own confirmation card (what, where, every field; no "Always").
  const previewRecord = readPreviewRecord(approval.changePreview);
  const texts = approvalTexts(approval, previewRecord);
  const writeView = connectorWriteView(previewRecord, approval.changePreview?.toolName);
  if (writeView) {
    return (
      <ConnectorWriteCard
        approval={approval}
        view={{ ...writeView, title: texts.title }}
        subtitle={texts.subtitle}
        onDecision={onDecision}
        actionsDisabled={actionsDisabled}
      />
    );
  }
  return <ApprovalInlineCard {...props} texts={texts} previewRecord={previewRecord} retry={retry} />;
}

// The rerun of a held request from its approval card, with its busy state.
function useApprovalRetry(
  approvalId: string,
  onRetryFromApproval: ApprovalBubbleProps["onRetryFromApproval"],
  retryPrompt: string | null | undefined,
  actionsDisabled: boolean,
) {
  const [retrying, setRetrying] = useState(false);

  async function triggerRetryFromApproval() {
    if (!onRetryFromApproval || !retryPrompt || actionsDisabled || retrying) {
      return;
    }
    setRetrying(true);
    try {
      await onRetryFromApproval(approvalId, retryPrompt);
    } finally {
      setRetrying(false);
    }
  }

  return { retrying, triggerRetryFromApproval };
}

function ApprovalInlineCard({
  approval,
  onDecision,
  onRetryFromApproval,
  onRetryFromChangePreview,
  retryPrompt,
  actionsDisabled = false,
  canGrantStandingConfirmation = false,
  texts,
  previewRecord,
  retry,
}: ApprovalBubbleProps & {
  texts: ReturnType<typeof approvalTexts>;
  previewRecord: ReturnType<typeof readPreviewRecord>;
  retry: ReturnType<typeof useApprovalRetry>;
}) {
  const { retrying, triggerRetryFromApproval } = retry;
  const card = approvalCardModel(approval, {
    canRetry: Boolean(retryPrompt && onRetryFromApproval),
    canGrantStandingConfirmation,
  });
  const view = approvalInlineView(approval, previewRecord, texts.subtitle);

  return (
    <article className="message-row message-row--approval">
      <div className={`approval-inline approval-inline--${view.approvalStatus}`}>
        <div className="approval-inline__icon">
          <ApprovalShieldIcon />
        </div>
        <ApprovalInlineBody title={texts.title} view={view} />
        <ApprovalInlineActions
          approval={approval}
          card={card}
          approvalStatus={view.approvalStatus}
          standingScope={standingRuleScopeLabel(approval.standingRule)}
          onDecision={onDecision}
          actionsDisabled={actionsDisabled}
          retrying={retrying}
          onRetry={() => void triggerRetryFromApproval()}
        />
      </div>
      {approval.changePreview || approval.reason ? (
        <ApprovalInlineDetails
          approval={approval}
          view={view}
          onRetryFromChangePreview={onRetryFromChangePreview}
          retryPrompt={retryPrompt}
          actionsDisabled={actionsDisabled}
        />
      ) : null}
    </article>
  );
}
