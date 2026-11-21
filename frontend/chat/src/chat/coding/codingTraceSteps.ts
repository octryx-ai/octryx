// The coding execution trace's steps (source, plan, workspace, agent run, changes, validation, delivery) from the run's evidence.
import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { recordValue } from "./codingSessionValues";
import {
  approvalLabel,
  codingApprovalEvidence,
  codingValidationEvidence,
  plannedCheckCount,
  validationLabel,
  validationToolCallLabel,
  validationStatusWord,
  validationTone,
} from "./codingEvidenceModel";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkCodingWorkspace } from "../work/workCodingPipelineTypes";

type TraceTone = "active" | "running" | "attention" | "danger" | "neutral";

export type TraceStep = {
  key: string;
  label: string;
  status: string;
  tone: TraceTone;
  summary: string;
  meta: string[];
  links: Array<{ label: string; href?: string | null }>;
};

export function buildTraceSteps(
  session: CodingSessionSummary,
  detail: CodingSessionDetailData | null,
  latestPlan: WorkChangePlan | null,
): TraceStep[] {
  const workspaces = workspaceRecords(detail);
  const observability = detail?.observability || null;
  const latestAgentSession = session.latestAgentSession;
  const pullRequestLinks = session.pullRequests.map((href) => ({ label: compactUrlLabel(href), href }));
  const repositoryLinks = repositoryLinksFromPlan(latestPlan);
  const branchLinks = branchLinksFromUnits(detail, latestPlan);
  const failedTools = observability?.summary.failed_tool_call_count || 0;
  // Recorded results and tool events only; a measured zero stays zero and planned checks never count.
  const sourceFields = recordValue(session.workItem.source_fields);
  const validation = codingValidationEvidence(sourceFields, latestPlan, observability);
  const approvals = codingApprovalEvidence(sourceFields, latestPlan);
  const mutationEvents = observability?.summary.mutation_event_count || 0;
  return [
    {
      key: "source",
      label: "Source task",
      status: session.workItem.source_status || session.workItem.work_state || "imported",
      tone: session.workItem.source_url ? "active" : "neutral",
      summary: session.title,
      meta: [
        `Jira ${session.workItem.source_project_key || "-"}`,
        `Assignee ${session.workItem.assignee || "unassigned"}`,
        `Labels ${(session.workItem.labels || []).join(", ") || "-"}`,
      ],
      links: [{ label: "Open Jira", href: session.workItem.source_url }],
    },
    {
      key: "plan",
      label: "Work plan",
      status: latestPlan?.status || "missing",
      tone: latestPlan?.status === "approved" ? "active" : latestPlan ? "attention" : "neutral",
      summary: latestPlan ? `${latestPlan.title} · v${latestPlan.version}` : "No Change Plan evidence captured.",
      meta: [
        `${latestPlan?.affected_repositories.length || session.repositories.length} repositories`,
        `${latestPlan?.planned_files.length || session.plannedFileCount} planned files`,
        `${plannedCheckCount(latestPlan)} planned checks`,
      ],
      links: [],
    },
    {
      key: "workspace",
      label: "Workspace & branch",
      status: workspaces.length ? workspaceStatus(workspaces) : "not prepared",
      tone: workspaces.some((workspace) => workspace.status === "prepared") ? "active" : workspaces.length ? "running" : "neutral",
      summary: workspaces.length
        ? `${workspaces.length} workspace record${workspaces.length === 1 ? "" : "s"} linked to this run.`
        : "No isolated workspace evidence is linked yet.",
      // Prepared workspace branches are recorded; plan and Change Unit branches are only planned.
      meta: uniqueStrings([
        ...workspaces.map((workspace) => workspace.feature_branch || ""),
        ...session.repositories,
        ...session.branches.map((branch) => `Planned: ${branch}`),
      ]).slice(0, 5),
      links: [...repositoryLinks, ...branchLinks].slice(0, 6),
    },
    {
      key: "agent",
      label: "Agent run",
      status: latestAgentSession?.run_status || latestAgentSession?.status || "not started",
      tone: latestAgentSession ? (failedTools > 0 ? "attention" : "running") : "neutral",
      summary: observability
        ? `${observability.summary.llm_call_count} LLM calls · ${formatNumber(observability.summary.total_tokens)} tokens · $${observability.summary.total_cost}`
        : "No runtime observability linked yet.",
      meta: observability
        ? [
          `${observability.summary.tool_call_count} tool calls`,
          `${observability.summary.repeated_tool_call_count} repeated`,
          `${failedTools} failed tools`,
        ]
        : [],
      links: latestAgentSession ? [{ label: "Open task chat", href: latestAgentSession.chat_url }] : [],
    },
    {
      key: "changes",
      label: "Changes",
      // Mutation-type tool calls are classified by tool name; they are calls, not a delivered change.
      status: pullRequestLinks.length ? "PR linked" : mutationEvents > 0 ? "tool calls recorded" : session.plannedFileCount > 0 ? "planned" : "pending",
      tone: pullRequestLinks.length ? "active" : mutationEvents > 0 || session.plannedFileCount > 0 ? "running" : "neutral",
      summary: mutationEvents > 0
        ? `${mutationEvents} mutation-type tool call${mutationEvents === 1 ? "" : "s"} recorded.`
        : "No mutation tool call is recorded yet.",
      meta: uniqueStrings([
        ...((latestPlan?.planned_files || []).map((entry) => stringValue(recordValue(entry)?.path || recordValue(entry)?.file))),
        ...(detail?.changeUnits || []).flatMap((unit) => unit.expected_paths),
      ]).slice(0, 6),
      links: [],
    },
    {
      key: "validation",
      label: "Validation",
      status: validationStatusWord(validation),
      tone: validationTone(validation),
      summary: validationLabel(validation),
      meta: [
        ...(latestPlan?.validation_plan || []).map((entry) => {
          const check = typeof entry === "string" ? entry : stringValue(recordValue(entry)?.command || recordValue(entry)?.name);
          return check ? `Planned: ${check}` : "";
        }),
        validationToolCallLabel(validation) || "",
      ].filter(Boolean).slice(0, 5),
      links: [],
    },
    {
      key: "delivery",
      label: "Delivery",
      status: pullRequestLinks.length ? "PR linked" : session.blockerCount > 0 ? "blocked" : "pending",
      tone: pullRequestLinks.length ? "active" : session.blockerCount > 0 ? "attention" : "neutral",
      summary: pullRequestLinks.length
        ? `${pullRequestLinks.length} pull request link${pullRequestLinks.length === 1 ? "" : "s"} captured.`
        : session.blockerCount > 0
          ? `${session.blockerCount} blocker${session.blockerCount === 1 ? "" : "s"} before delivery.`
          : "No PR or blocker outcome captured yet.",
      meta: [
        `Recommended reviewers ${(detail?.reviewerPayload?.recommendations || []).length}`,
        `Approvals ${approvalLabel(approvals)}`,
      ],
      links: pullRequestLinks,
    },
  ];
}

function workspaceRecords(detail: CodingSessionDetailData | null): WorkCodingWorkspace[] {
  const run = detail?.pipelineTrace?.run;
  const summary = recordValue(run?.summary);
  const recoveryState = recordValue(run?.recovery_state);
  return [
    ...arrayValue(summary?.workspaces),
    ...arrayValue(recoveryState?.workspaces),
  ].filter(isWorkspaceRecord);
}

function isWorkspaceRecord(value: unknown): value is WorkCodingWorkspace {
  const workspace = recordValue(value);
  return Boolean(
    workspace &&
      typeof workspace.id === "string" &&
      typeof workspace.work_item_id === "string" &&
      typeof workspace.status === "string",
  );
}

function repositoryLinksFromPlan(latestPlan: WorkChangePlan | null): Array<{ label: string; href?: string | null }> {
  return uniqueRecords(
    (latestPlan?.affected_repositories || []).map((entry) => {
      const repository = recordValue(entry);
      const label = stringValue(repository?.repository_name || repository?.name);
      const href = stringValue(repository?.repository_url || repository?.url);
      return { label, href };
    }),
  );
}

function branchLinksFromUnits(
  detail: CodingSessionDetailData | null,
  latestPlan: WorkChangePlan | null,
): Array<{ label: string; href?: string | null }> {
  const repositoryUrls = new Map(repositoryLinksFromPlan(latestPlan).map((entry) => [entry.label, entry.href || ""]));
  return uniqueRecords(
    (detail?.changeUnits || []).map((unit) => ({
      label: unit.branch_name,
      href: branchBrowseUrl(repositoryUrls.get(unit.repository_name), unit.branch_name),
    })),
  );
}

function workspaceStatus(workspaces: WorkCodingWorkspace[]): string {
  const prepared = workspaces.filter((workspace) => workspace.status === "prepared").length;
  if (prepared === workspaces.length) return "prepared";
  if (prepared > 0) return "partially prepared";
  return workspaces[0]?.status || "recorded";
}

function branchBrowseUrl(repositoryUrl?: string | null, branchName?: string | null): string | null {
  const branch = String(branchName || "").trim();
  const rawUrl = String(repositoryUrl || "").trim();
  if (!branch || !isHttpUrl(rawUrl)) return null;
  const browseUrl = rawUrl.includes("/browse") ? rawUrl : `${rawUrl.replace(/\/$/, "")}/browse`;
  const separator = browseUrl.includes("?") ? "&" : "?";
  return `${browseUrl}${separator}at=${encodeURIComponent(`refs/heads/${branch}`)}`;
}

function compactUrlLabel(url: string): string {
  const value = url.trim();
  if (!isHttpUrl(value)) return value;
  const pullRequestMatch = value.match(/pull-requests\/([^/?#]+)/i);
  if (pullRequestMatch) return `PR ${pullRequestMatch[1]}`;
  const parts = value.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || value;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function uniqueRecords(records: Array<{ label: string; href?: string | null }>): Array<{ label: string; href?: string | null }> {
  const seen = new Set<string>();
  return records.filter((record) => {
    const key = `${record.label}:${record.href || ""}`;
    if (!record.label || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function arrayValue(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value == null || value === "") return [];
  return [value];
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
