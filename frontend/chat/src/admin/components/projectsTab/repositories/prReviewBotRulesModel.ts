// Workspace settings › Repositories › PR review bot › "Rule proposals": the team rules `@octryx ignore` proposes
// (stage D1b, backend services/pr_review_bot/rule_proposals.py, routes api/routes/pr_review_bot.py). Pure: no React.
//
// - GET  /api/v1/workspaces/<ws>/pr-review-bot/rule-proposals → {proposals: [...], can_edit}, newest first; members
//   read.
// - POST …/rule-proposals/<id>/accept {rule?} appends the (edited) rule to the repository's code style rules;
//   POST …/rule-proposals/<id>/reject closes it. Both answer {proposal}. Admins/owners only.
// Refusals are `{state: "denied", reason}`.

export type ProposalState = "open" | "accepted" | "rejected";

export type RuleProposal = {
  id: string;
  state: ProposalState;
  repositoryId: string;
  file: string;
  rule: string;
  reason: string;
  finding: { severity: string; file: string; line: number | null; fix: string };
  proposedBy: string;
  prUrl: string;
  createdAt: string;
  decidedAt: string;
};

export type ProposalsPayload = { proposals: RuleProposal[]; canEdit: boolean };

/** The server cuts a rule at this many characters; the editor stops there too. */
export const MAX_RULE = 500;

export const ACCEPTED_LINE = "Active team rule in the code style of this repository.";

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const text = (value: unknown) => (typeof value === "string" ? value : "");
const STATES: readonly ProposalState[] = ["open", "accepted", "rejected"];

/** One proposal; null without an id. An unknown state reads as decided (rejected) so nobody acts on it. */
export function readProposal(raw: unknown): RuleProposal | null {
  const row = record(raw);
  const id = text(row.id);
  if (!id) return null;
  const finding = record(row.finding);
  const state = text(row.state) as ProposalState;
  const line = typeof finding.line === "number" && Number.isFinite(finding.line) ? finding.line : null;
  return {
    id,
    state: STATES.includes(state) ? state : "rejected",
    repositoryId: text(row.repository_id),
    file: text(row.file) || text(finding.file),
    rule: text(row.rule),
    reason: text(row.reason),
    finding: { severity: text(finding.severity), file: text(finding.file), line, fix: text(finding.fix) },
    proposedBy: text(row.proposed_by),
    prUrl: /^https?:\/\//.test(text(row.pr_url)) ? text(row.pr_url) : "",
    createdAt: text(row.created_at),
    decidedAt: text(row.decided_at),
  };
}

export function readProposals(raw: unknown): ProposalsPayload {
  const body = record(raw);
  const rows = Array.isArray(body.proposals) ? body.proposals : [];
  return {
    proposals: rows.map(readProposal).filter((row): row is RuleProposal => row !== null),
    canEdit: body.can_edit === true,
  };
}

/** One repository's proposals: the open ones (newest first, as the server sends them) and the decided ones. */
export function proposalsFor(all: RuleProposal[], repositoryId: string) {
  const mine = all.filter((row) => row.repositoryId === repositoryId);
  return { open: mine.filter((row) => row.state === "open"), decided: mine.filter((row) => row.state !== "open") };
}

/** The server folds whitespace; so does the comparison and the editor's problem check. */
export const foldRule = (value: string) => value.split(/\s+/).filter(Boolean).join(" ");

/** A problem with the edited rule text, or null. */
export function ruleProblem(draft: string): string | null {
  const folded = foldRule(draft);
  if (!folded) return "The rule needs some text.";
  if (folded.length > MAX_RULE) return `The rule can have at most ${MAX_RULE} characters (now ${folded.length}).`;
  return null;
}

/** Accept sends the text only when the admin changed it; the server then keeps its own wording otherwise. */
export function acceptBody(proposal: RuleProposal, draft: string): { rule?: string } {
  const edited = foldRule(draft);
  return edited && edited !== foldRule(proposal.rule) ? { rule: edited } : {};
}

/** "high · pay/bulk.py:42" — the finding the rule came from. */
export function findingLine(proposal: RuleProposal): string {
  const where = proposal.finding.file || proposal.file;
  const place = where ? `${where}${proposal.finding.line !== null ? `:${proposal.finding.line}` : ""}` : "";
  return [proposal.finding.severity, place].filter(Boolean).join(" · ");
}

export function stateLabel(state: ProposalState): string {
  return state === "open" ? "Open" : state === "accepted" ? "Accepted" : "Rejected";
}

/** The line under a decided proposal. */
export function decidedLine(proposal: RuleProposal, day: (iso: string) => string): string {
  if (proposal.state === "accepted") return ACCEPTED_LINE;
  const when = proposal.decidedAt ? day(proposal.decidedAt) : "";
  return when ? `Rejected on ${when}. The finding will be reported again.` : "Rejected. The finding will be reported again.";
}

/** The note after a decision. */
export function decisionText(decision: "accept" | "reject"): string {
  return decision === "accept"
    ? "Accepted. The bot follows this rule from the next review on."
    : "Rejected. Nothing changed in the code style.";
}

/** A refused decision in words; `proposal_decided` also means the list should be read again. */
export function decisionErrorText(status: number, body: unknown): string {
  const reason = text(record(body).reason);
  switch (reason) {
    case "workspace_admin_required": return "Only Workspace admins and owners can decide rule proposals.";
    case "proposal_decided": return "Someone already decided this proposal. The list now shows the current state.";
    case "proposal_not_found": return "This proposal no longer exists.";
    case "repository_not_found": return "The repository of this proposal is no longer in this Workspace.";
    case "workspace_not_found": return "This Workspace no longer exists, or you are no longer a member.";
    case "invalid_rules": return "The code style rules of this repository are full (3000 characters). Shorten them first, then accept.";
  }
  if (status === 0) return "The decision did not reach the server. Try again.";
  return reason ? `The code style refused this rule (${reason}).` : "The decision could not be saved. Try again.";
}

/** The GET's problem: null when the server answers 404 without a reason (no proposals route: show nothing). */
export function proposalsLoadProblem(status: number, body: unknown): string | null {
  if (status === 404 && record(body).reason === undefined) return null;
  if (status === 0) return "The rule proposals could not be loaded: the request did not reach the server.";
  return "The rule proposals could not be loaded. Try again.";
}

/** Replace one proposal with the server's answer. */
export function withDecided(all: RuleProposal[], decided: RuleProposal): RuleProposal[] {
  return all.map((row) => (row.id === decided.id ? decided : row));
}
