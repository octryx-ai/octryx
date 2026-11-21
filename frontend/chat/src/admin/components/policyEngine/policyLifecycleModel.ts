// Pure model of the lifecycle drawer and the impact examples: the review of a version as
// the server describes it for the viewer, the version history with author and reviewer, a line diff of two set
// texts, and the generated impact examples with their answers.

import { readTestReport } from "./policyEngineVersions";
import type { TestReport } from "./policyEngineVersions";

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const records = (value: unknown): Json[] => (Array.isArray(value) ? value.filter(isRecord) : []);
const person = (value: unknown) => (isRecord(value) ? { id: str(value.id), name: str(value.name) || str(value.id) } : null);

export type Review = {
  approvalId: string; status: string; requestedBy: { id: string; name: string } | null; requestedAt: string;
  decidedBy: { id: string; name: string } | null; comment: string; author: { id: string; name: string } | null;
  submitter: { id: string; name: string } | null; candidates: { id: string; name: string }[];
  viewer: { isAuthor: boolean; isSubmitter: boolean; canApprove: boolean }; singleAdmin: boolean; rule: string;
};

export function readReview(raw: unknown): Review | null {
  const value = isRecord(raw) && isRecord(raw.review) ? raw.review : null;
  if (!value) return null;
  const viewer = isRecord(value.viewer) ? value.viewer : {};
  return {
    approvalId: str(value.approval_id), status: str(value.status), requestedBy: person(value.requested_by),
    requestedAt: str(value.requested_at), decidedBy: person(value.decided_by), comment: str(value.comment),
    author: person(value.author), submitter: person(value.submitter),
    candidates: records(value.approver_candidates).map((item) => ({ id: str(item.id), name: str(item.name) || str(item.id) })),
    viewer: { isAuthor: viewer.is_author === true, isSubmitter: viewer.is_submitter === true, canApprove: viewer.can_approve === true },
    singleAdmin: value.single_admin === true, rule: str(value.rule),
  };
}

export type HistoryRow = {
  version: number; state: string; note: string; authorName: string; reviewerName: string; publishedAt: string;
  /** `self` when the author approved their own version (approval rule: single admin). */
  approvalMode: string;
};

export function readHistory(raw: unknown): HistoryRow[] {
  const items = isRecord(raw) ? records(raw.items) : [];
  return items.filter((item) => typeof item.version === "number").map((item) => ({
    version: item.version as number, state: str(item.state), note: str(item.note), authorName: str(item.author_name) || str(item.created_by),
    reviewerName: str(item.reviewer_name), publishedAt: str(item.published_at), approvalMode: str(item.approval_mode),
  }));
}

export type DiffLine = { kind: "same" | "added" | "removed"; text: string };
const MAX_DIFF_CELLS = 4_000_000;

/** A line diff (longest common subsequence); `null` when the texts are too large to diff in the browser. */
export function lineDiff(before: string, after: string): DiffLine[] | null {
  const a = before ? before.replace(/\n$/, "").split("\n") : [];
  const b = after ? after.replace(/\n$/, "").split("\n") : [];
  if (a.length * b.length > MAX_DIFF_CELLS) return null;
  const table = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { lines.push({ kind: "same", text: a[i] }); i += 1; j += 1; }
    else if (table[i + 1][j] >= table[i][j + 1]) { lines.push({ kind: "removed", text: a[i] }); i += 1; }
    else { lines.push({ kind: "added", text: b[j] }); j += 1; }
  }
  while (i < a.length) { lines.push({ kind: "removed", text: a[i] }); i += 1; }
  while (j < b.length) { lines.push({ kind: "added", text: b[j] }); j += 1; }
  return lines;
}

export type ImpactExample = {
  name: string; kind: "block" | "control"; expected: string; request: Json;
  answer: { decision: string; determining: string[]; byThisPolicy: boolean; asExpected: boolean; error: string; notes: string[] };
};
export type Impact = { workspaceName: string; notes: string[]; policySource: string; examples: ImpactExample[]; cases: TestReport | null };

export function readImpact(raw: unknown): Impact {
  const value = isRecord(raw) ? raw : {};
  const workspace = isRecord(value.workspace) ? value.workspace : {};
  return {
    workspaceName: str(workspace.name),
    notes: Array.isArray(value.notes) ? value.notes.filter((item): item is string => typeof item === "string") : [],
    policySource: str(value.policy_source),
    examples: records(value.examples).map((item) => {
      const answer = isRecord(item.answer) ? item.answer : {};
      return {
        name: str(item.name), kind: item.kind === "control" ? "control" : "block", expected: str(item.expected),
        request: isRecord(item.request) ? item.request : {},
        answer: {
          decision: str(answer.decision),
          determining: Array.isArray(answer.determining) ? answer.determining.filter((entry): entry is string => typeof entry === "string") : [],
          byThisPolicy: answer.by_this_policy === true, asExpected: answer.as_expected === true, error: str(answer.error),
          notes: Array.isArray(answer.notes) ? answer.notes.filter((entry): entry is string => typeof entry === "string") : [],
        },
      };
    }),
    cases: readTestReport(value.cases),
  };
}

/** A saved test case from an example. It records the policy's intent (an example to block expects deny, the control
 * expects allow), so a policy that does not do what it should fails its case and publishing is refused. */
export const exampleCase = (example: ImpactExample, policyName: string) => ({
  name: `${policyName}: ${example.name}`.slice(0, 120),
  expected: example.kind === "control" ? "allow" : "deny",
  request: example.request,
});

export type DraftPolicyImpact = {
  count: number; points: Record<string, number>; actions: Record<string, number>; principals: number;
  samples: { time: string; point: string; action: string; principal: string; resource: string; workspaceId: string }[];
};
export type DraftImpact = { version: number; hours: number; total: number; policies: Record<string, DraftPolicyImpact> };

const counts = (value: unknown): Record<string, number> => (isRecord(value)
  ? Object.fromEntries(Object.entries(value).filter(([, count]) => typeof count === "number") as [string, number][]) : {});

export function readDraftImpact(raw: unknown): DraftImpact | null {
  if (!isRecord(raw) || typeof raw.version !== "number") return null;
  const policies = isRecord(raw.policies) ? raw.policies : {};
  return {
    version: raw.version, hours: typeof raw.hours === "number" ? raw.hours : 24, total: typeof raw.total === "number" ? raw.total : 0,
    policies: Object.fromEntries(Object.entries(policies).filter(([, value]) => isRecord(value)).map(([id, value]) => {
      const item = value as Json;
      return [id, {
        count: typeof item.count === "number" ? item.count : 0, points: counts(item.points), actions: counts(item.actions),
        principals: typeof item.principals === "number" ? item.principals : 0,
        samples: records(item.samples).map((sample) => ({ time: str(sample.time), point: str(sample.point), action: str(sample.action),
          principal: str(sample.principal), resource: str(sample.resource), workspaceId: str(sample.workspace_id) })),
      }];
    })),
  };
}

/** "12 × call_tool, 2 × write_connector" — the largest first. */
export const actionBreakdown = (impact: DraftPolicyImpact) =>
  Object.entries(impact.actions).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([action, count]) => `${count} × ${action}`).join(", ");
