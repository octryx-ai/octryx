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

// The server cuts a rule at this many characters.
export const MAX_RULE = 500;

export const ACCEPTED_LINE = "Active team rule in the code style of this repository.";

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const text = (value: unknown) => (typeof value === "string" ? value : "");
const STATES: readonly ProposalState[] = ["open", "accepted", "rejected"];

// An unknown state reads as decided, so nobody acts on it.
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

export function proposalsFor(all: RuleProposal[], repositoryId: string) {
  const mine = all.filter((row) => row.repositoryId === repositoryId);
  return { open: mine.filter((row) => row.state === "open"), decided: mine.filter((row) => row.state !== "open") };
}

// The server folds whitespace the same way.
export const foldRule = (value: string) => value.split(/\s+/).filter(Boolean).join(" ");

export function ruleProblem(draft: string): string | null {
  const folded = foldRule(draft);
  if (!folded) return "The rule needs some text.";
  if (folded.length > MAX_RULE) return `The rule can have at most ${MAX_RULE} characters (now ${folded.length}).`;
  return null;
}

// Only an edited text is sent; otherwise the server keeps its own wording.
export function acceptBody(proposal: RuleProposal, draft: string): { rule?: string } {
  const edited = foldRule(draft);
  return edited && edited !== foldRule(proposal.rule) ? { rule: edited } : {};
}

export function findingLine(proposal: RuleProposal): string {
  const where = proposal.finding.file || proposal.file;
  const place = where ? `${where}${proposal.finding.line !== null ? `:${proposal.finding.line}` : ""}` : "";
  return [proposal.finding.severity, place].filter(Boolean).join(" · ");
}

export function stateLabel(state: ProposalState): string {
  return state === "open" ? "Open" : state === "accepted" ? "Accepted" : "Rejected";
}

export function decidedLine(proposal: RuleProposal, day: (iso: string) => string): string {
  if (proposal.state === "accepted") return ACCEPTED_LINE;
  const when = proposal.decidedAt ? day(proposal.decidedAt) : "";
  return when ? `Rejected on ${when}. The finding will be reported again.` : "Rejected. The finding will be reported again.";
}

export function decisionText(decision: "accept" | "reject"): string {
  return decision === "accept"
    ? "Accepted. The bot follows this rule from the next review on."
    : "Rejected. Nothing changed in the code style.";
}

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

// A 404 without a reason means no proposals route: show nothing.
export function proposalsLoadProblem(status: number, body: unknown): string | null {
  if (status === 404 && record(body).reason === undefined) return null;
  if (status === 0) return "The rule proposals could not be loaded: the request did not reach the server.";
  return "The rule proposals could not be loaded. Try again.";
}

export function withDecided(all: RuleProposal[], decided: RuleProposal): RuleProposal[] {
  return all.map((row) => (row.id === decided.id ? decided : row));
}
