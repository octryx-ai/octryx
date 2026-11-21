import { useState } from "react";

import { EmptyLine } from "../../../../layout/EmptyLine";
import { StatusLabel } from "../../../../layout/StatusLabel";
import {
  MAX_RULE,
  acceptBody,
  decidedLine,
  decisionErrorText,
  decisionText,
  findingLine,
  foldRule,
  proposalsFor,
  readProposal,
  ruleProblem,
  stateLabel,
  type RuleProposal,
} from "./prReviewBotRulesModel";
import { call } from "./reviewBotApi";
import { day, proposalsPath, type RuleProposalsState } from "./useRuleProposals";

// Inside one repository card: open proposals first (editable for admins), decided ones folded below.
export function RuleProposalsBlock({ workspaceId, repositoryId, repositoryName, rules }: {
  workspaceId: string;
  repositoryId: string;
  repositoryName: string;
  rules: RuleProposalsState;
}) {
  const { payload, problem } = rules;
  // Still loading, or no proposals route (proposalsLoadProblem): nothing.
  if (!payload && !problem) return null;
  const testId = `review-bot-${repositoryId}-rules`;
  const mine = payload ? proposalsFor(payload.proposals, repositoryId) : { open: [], decided: [] };

  return (
    <div className="review-bot__field review-bot__rules" data-testid={testId}>
      <div className="review-bot__label">Rule proposals</div>
      <p className="sk-muted">
        When someone answers a finding with <code>@octryx ignore</code> and a reason, the bot proposes a team rule.
        Accepted rules go into this repository's code style; the bot follows them from the next review on.
      </p>
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      {payload && !mine.open.length && !mine.decided.length ? (
        <EmptyLine text="No rule proposals for this repository." testId={`${testId}-empty`} />
      ) : null}
      {mine.open.map((proposal) => (
        <OpenProposal key={proposal.id} workspaceId={workspaceId} proposal={proposal} repositoryName={repositoryName}
          canEdit={payload?.canEdit === true} rules={rules} />
      ))}
      {payload && !payload.canEdit && mine.open.length ? (
        <p className="sk-muted" data-testid={`${testId}-readonly`}>Only Workspace admins and owners can accept or reject proposals.</p>
      ) : null}
      {mine.decided.length ? (
        <details className="review-bot__decided" data-testid={`${testId}-decided`}>
          <summary>Decided ({mine.decided.length})</summary>
          {mine.decided.map((proposal) => <DecidedProposal key={proposal.id} proposal={proposal} />)}
        </details>
      ) : null}
    </div>
  );
}

function ProposalFacts({ proposal }: { proposal: RuleProposal }) {
  const finding = findingLine(proposal);
  return (
    <dl className="review-bot__facts">
      {finding ? <><dt>Finding</dt><dd>{finding}{proposal.finding.fix ? <span className="sk-muted"> — {proposal.finding.fix}</span> : null}</dd></> : null}
      {proposal.reason ? <><dt>Reason</dt><dd>{proposal.reason}</dd></> : null}
      <dt>Proposed</dt>
      <dd>
        {[proposal.proposedBy && `by ${proposal.proposedBy}`, day(proposal.createdAt)].filter(Boolean).join(", ") || "—"}
        {proposal.prUrl ? <> · <a href={proposal.prUrl} target="_blank" rel="noreferrer">Pull request</a></> : null}
      </dd>
    </dl>
  );
}

function OpenProposal({ workspaceId, proposal, repositoryName, canEdit, rules }: {
  workspaceId: string;
  proposal: RuleProposal;
  repositoryName: string;
  canEdit: boolean;
  rules: RuleProposalsState;
}) {
  const [draft, setDraft] = useState(proposal.rule);
  const [busy, setBusy] = useState<"accept" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const problem = ruleProblem(draft);
  const edited = foldRule(draft) !== foldRule(proposal.rule);
  const testId = `review-bot-rule-${proposal.id}`;

  async function decide(decision: "accept" | "reject") {
    setBusy(decision); setError(null);
    const body = decision === "accept" ? acceptBody(proposal, draft) : undefined;
    const answer = await call(`${proposalsPath(workspaceId)}/${encodeURIComponent(proposal.id)}/${decision}`, "POST", body);
    setBusy(null);
    const decided = answer.ok ? readProposal((answer.body as { proposal?: unknown } | null)?.proposal) : null;
    if (decided) { rules.replace(decided); return; }
    setError(decisionErrorText(answer.ok ? 500 : answer.status, answer.body));
    if ((answer.body as { reason?: unknown } | null)?.reason === "proposal_decided") rules.reload();
  }

  return (
    <div className="review-bot__proposal" data-testid={testId}>
      <div className="review-bot__proposal-head">
        <span className="review-bot__proposal-file">{proposal.file || "Whole repository"}</span>
        <StatusLabel label={stateLabel(proposal.state)} tone="attention" />
      </div>
      {canEdit ? (
        <label className="review-bot__rule-edit">
          <span className="sk-muted">Rule{edited ? " (edited)" : ""}</span>
          <textarea className="admin-panel__input review-bot__rule-input" rows={3} value={draft} disabled={busy !== null}
            aria-label={`Rule proposed for ${repositoryName}`} maxLength={MAX_RULE * 2} data-testid={`${testId}-text`}
            onChange={(event) => { setDraft(event.target.value); setError(null); }} />
          <span className={problem ? "sk-err" : "sk-muted"} data-testid={`${testId}-count`}>
            {problem ?? `${foldRule(draft).length} / ${MAX_RULE}`}
          </span>
        </label>
      ) : (
        <p className="review-bot__rule-text" data-testid={`${testId}-text`}>{proposal.rule}</p>
      )}
      <ProposalFacts proposal={proposal} />
      {canEdit ? (
        <div className="sk-row review-bot__actions">
          {edited ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
              onClick={() => { setDraft(proposal.rule); setError(null); }}>Undo edit</button>
          ) : null}
          <button type="button" className="admin-panel__action-btn" disabled={busy !== null} data-testid={`${testId}-reject`}
            onClick={() => void decide("reject")}>{busy === "reject" ? "Rejecting…" : "Reject"}</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={`${testId}-accept`}
            disabled={busy !== null || problem !== null} onClick={() => void decide("accept")}>
            {busy === "accept" ? "Accepting…" : edited ? "Accept edited rule" : "Accept"}
          </button>
        </div>
      ) : null}
      {error ? <p className="sk-err" role="alert" data-testid={`${testId}-error`}>{error}</p> : null}
    </div>
  );
}

function DecidedProposal({ proposal }: { proposal: RuleProposal }) {
  return (
    <div className="review-bot__proposal review-bot__proposal--decided" data-testid={`review-bot-rule-${proposal.id}`}>
      <div className="review-bot__proposal-head">
        <span className="review-bot__proposal-file">{proposal.file || "Whole repository"}</span>
        <StatusLabel label={stateLabel(proposal.state)} tone="neutral" />
      </div>
      <p className="review-bot__rule-text">{proposal.rule}</p>
      <p className="sk-muted" data-testid={`review-bot-rule-${proposal.id}-decided`}>{decidedLine(proposal, day)}</p>
      <ProposalFacts proposal={proposal} />
    </div>
  );
}
