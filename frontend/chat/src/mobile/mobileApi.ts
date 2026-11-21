// Octryx Mobile's data requests (chats, runs, tasks, devices, push); the session and pairing live in mobileSession.

import type { WorkflowOption } from "../chatOptionTypes";
import type { WorkflowProposalView } from "../chatDecisionTypes";
import type { ProposalAnswerBody } from "../chat/run/workflowProposalAnswer";
import { api, startSession } from "./mobileSession";

// --- the app's data --------------------------------------------------------------------------------------------

export const loadBootstrap = () =>
  api<Record<string, unknown>>("/chat/api/bootstrap");
export const loadUsage = (workspaceId: string) =>
  api<unknown>(
    `/api/v1/mobile/usage?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
export const loadAttentionQueue = () => api<unknown>("/api/v1/attention");
export const loadDevices = () => api<unknown>("/api/v1/devices");
// Roles, read-only (roles contract §3.3): the person's own roles; the Workspace's assignments answer only its admins.
const rolesPath = (workspaceId: string) => `/api/v1/work-roles/workspaces/${encodeURIComponent(workspaceId)}`;
export const loadMyRole = (workspaceId: string) => api<unknown>(`${rolesPath(workspaceId)}/me`);
export const loadWorkspaceRoles = (workspaceId: string) => api<unknown>(rolesPath(workspaceId));
export const loadPolicy = (projectId: string) =>
  api<unknown>(
    `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/device-runs`,
  );
// The Workspace's seat switches, read-only on the phone (a phone surface since; PUT stays off it).
export const loadSeatMode = (projectId: string) =>
  api<unknown>(`/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/seat-mode`);
export const loadMessages = (sessionId: string) =>
  api<{ messages: unknown[] }>(
    `/chat/api/sessions/${encodeURIComponent(sessionId)}/messages?limit=40`,
  );
// Phase B2: ``known`` ("job:seq,…") makes those jobs answer only newer events.
export const loadJobs = (sessionId: string, known = "") =>
  api<unknown>(
    `/api/v1/device-jobs?session_id=${encodeURIComponent(sessionId)}${
      known ? `&known=${encodeURIComponent(known)}` : ""
    }`,
  );
export const decide = (
  jobId: string,
  approvalId: string,
  decision: "allow_once" | "allow_job_edits" | "deny",
) =>
  api<unknown>(
    `/api/v1/device-jobs/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(approvalId)}`,
    { method: "POST", body: JSON.stringify({ decision }) },
  );
export const stopJob = (jobId: string) =>
  api<unknown>(`/api/v1/device-jobs/${encodeURIComponent(jobId)}/stop`, {
    method: "POST",
  });
export const send = (body: Record<string, unknown>) =>
  api<{ selectedSession?: { id?: string } }>("/chat/api/send", {
    method: "POST",
    body: JSON.stringify(body),
  });

// The person's open octryx-claude sessions (terminal, VS Code).
export const loadOpenSessions = () => api<unknown>("/api/v1/mobile/sessions");

// Claude Code sessions outside octryx on the person's Macs, and taking one over.
export const loadLocalSessions = () =>
  api<unknown>("/api/v1/mobile/local-sessions");
// Live: the Claude Code sessions running on the person's Macs (only their own web or phone login).
export const loadLive = () => api<unknown>("/api/v1/mobile/live");

export const loadLiveMessages = (deviceId: string, peer: string) =>
  api<unknown>(
    `/api/v1/mobile/live/messages?device_id=${encodeURIComponent(deviceId)}&peer=${encodeURIComponent(peer)}`,
  );

// What a listed session is doing (phase A): only events newer than ``sinceSeq``.
export const loadLiveProgress = (deviceId: string, peer: string, sinceSeq = 0) =>
  api<unknown>(
    `/api/v1/mobile/live/progress?device_id=${encodeURIComponent(deviceId)}&peer=${encodeURIComponent(peer)}&since_seq=${sinceSeq}`,
  );

export const sendLive = (deviceId: string, peer: string, text: string, images: string[] = []) =>
  api<{ message: unknown }>("/api/v1/mobile/live/messages", {
    method: "POST",
    body: JSON.stringify({
      device_id: deviceId,
      peer,
      text,
      ...(images.length ? { images: images.map((data) => ({ data })) } : {}),
    }),
  });

// Files a turn made on the Mac, fetched on request (only the person's own web or phone login).
export type MacFileState = {
  id: string;
  state: string;
  reason: string;
  size: number | null;
};

export const requestMacFile = (jobId: string, path: string) =>
  api<{ file: MacFileState }>(
    `/api/v1/device-jobs/${encodeURIComponent(jobId)}/files`,
    { method: "POST", body: JSON.stringify({ path }) },
  );

export const macFileState = (jobId: string, fileId: string) =>
  api<{ file: MacFileState }>(
    `/api/v1/device-jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(fileId)}`,
  );

export const macFileUrl = (jobId: string, fileId: string, download = false) =>
  `/api/v1/device-jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(fileId)}/content${download ? "?download=true" : ""}`;

// Artifacts of a Server chat: a page or an Office file as HTML (shown sandboxed, never as the app),
// a diagram as a picture the platform renders.
export async function loadArtifactPage(path: string): Promise<string> {
  const url = `/chat/api/artifact-preview?${new URLSearchParams({ path })}`;
  let response = await fetch(url, { credentials: "same-origin" });
  if (response.status === 401) {
    await startSession();
    response = await fetch(url, { credentials: "same-origin" });
  }
  if (!response.ok) throw Object.assign(new Error(`artifact_${response.status}`), { status: response.status, code: null });
  return response.text();
}
export const artifactImageUrl = (path: string) => `/chat/api/artifact-image?${new URLSearchParams({ path })}`;

// Cases: Work items with the automation label and the runs of the person's scope; a run is read and steered here.
// Starting a run for a task: the workflows, where it may run, the start (the web's body).
export const loadStartable = (projectId: string) =>
  api<{ workflows?: unknown }>(`/api/v1/workflow-runs/startable?project_id=${encodeURIComponent(projectId)}`);
export const loadRuntimeTargets = (projectId: string) =>
  api<unknown>(`/api/v1/workflow-runs/runtime-targets?project_id=${encodeURIComponent(projectId)}`);
export const startRun = (body: Record<string, unknown>) =>
  api<{ run: unknown; session_id: string }>("/api/v1/workflow-runs", { method: "POST", body: JSON.stringify(body) });

// A task's detail and its change plans; both are scoped to the person's Workspaces.
export const loadTask = (id: string) => api<unknown>(`/api/v1/secure-work/work-items/${encodeURIComponent(id)}`);
export const loadTaskPlans = (id: string) =>
  api<unknown>(`/api/v1/secure-work/work-items/${encodeURIComponent(id)}/change-plans`);

// The open task list: unfinished Work items, mine or all, by state, searched, with the counts.
// `project`: one Workspace (the phone's Workspace choice); empty: every Workspace of the person's scope.
export type TaskQuery = { mine?: boolean; state?: string; q?: string; offset?: number; limit?: number; project?: string };
export const loadTasks = ({ mine = false, state = "", q = "", offset = 0, limit = 50, project = "" }: TaskQuery = {}) => {
  const params = new URLSearchParams({ open: "true", state_counts: "true", limit: String(limit), offset: String(offset) });
  if (mine) params.set("mine", "true");
  if (project) params.set("project_id", project);
  if (state) params.set("work_state", state);
  if (q.trim()) params.set("q", q.trim().slice(0, 100));
  return api<unknown>(`/api/v1/secure-work/work-items?${params}`);
};
export const loadCaseRuns = (project = "") =>
  api<unknown>(`/api/v1/workflow-runs${project ? `?project_id=${encodeURIComponent(project)}` : ""}`);
// The Runs tab: Work › Runs' rows (step, cost, Work item), of one Workspace or all of the person's scope.
export const loadRuns = (project = "") =>
  api<unknown>(`/api/v1/workflow-runs?view=work${project ? `&project_id=${encodeURIComponent(project)}` : ""}`);
export const loadRun = (runId: string) =>
  api<{ run: unknown }>(`/api/v1/workflow-runs/${encodeURIComponent(runId)}`);
export const postRunAction = (path: string, body: Record<string, unknown>) =>
  api<{ run: unknown }>(path, { method: "POST", body: JSON.stringify(body) });

export const takeOver = (localId: string, message: string, threadId = "") =>
  api<{ thread_id: string; job_id: string; workspace_id: string }>(
    `/api/v1/mobile/local-sessions/${encodeURIComponent(localId)}/messages`,
    { method: "POST", body: JSON.stringify({ message, ...(threadId ? { thread_id: threadId } : {}) }) },
  );

// Phase B: continue a copy of an idle listed session as a Mac chat; the original stays untouched.
export type ForkStarted = { thread_id: string; job_id: string; workspace_id: string; local_id: string; title: string };
export const forkLive = (deviceId: string, peer: string, message: string) =>
  api<ForkStarted>("/api/v1/mobile/live/fork", {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, peer, message }),
  });

// This phone's notifications (Web Push).
export type PushRules = { needs_you: boolean; problem: boolean; done: boolean };
export type PushState = {
  configured: boolean;
  public_key: string | null;
  subscribed: boolean;
  rules: PushRules;
};
export const loadPush = () => api<PushState>("/api/v1/mobile/push");
export const savePush = (body: {
  subscription?: PushSubscriptionJSON;
  rules?: Partial<PushRules>;
}) =>
  api<PushState>("/api/v1/mobile/push", {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const deletePush = () =>
  api<PushState>("/api/v1/mobile/push", { method: "DELETE" });

// The models a device job may use for this profile in this Workspace (the chat's model picker on the Mac).
export const loadDeviceModels = (
  projectId: string,
  profile: string,
  deviceId: string,
) =>
  api<unknown>(
    `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/device-runs/models?profile=${encodeURIComponent(profile)}&device_id=${encodeURIComponent(deviceId)}`,
  );

// A Workspace's Server choices (models) for a new chat there.
export const loadWorkspaceChoices = (projectId: string) =>
  api<unknown>(
    `/chat/api/bootstrap?new=1&project_id=${encodeURIComponent(projectId)}`,
  );

// A Server chat's state (its pending approvals: a connector write waits for the person).
export const loadSessionView = (sessionId: string) =>
  api<{
    selectedApprovals?: unknown[];
    currentUser?: { id?: string };
    selectedSession?: { workflowProposal?: WorkflowProposalView | null } | null;
  }>(`/chat/api/sessions/${encodeURIComponent(sessionId)}/view`);
// A held workflow proposal (start card, "Other workflow…"): the same endpoint and body as the web
// (`workflowStartModel.proposalAnswerBody`); it answers with the chat's state.
export const answerWorkflowProposal = (sessionId: string, body: ProposalAnswerBody) =>
  api<{ selectedSession?: { workflowProposal?: WorkflowProposalView | null } | null }>(
    `/chat/api/sessions/${encodeURIComponent(sessionId)}/workflow-proposal`,
    { method: "POST", body: JSON.stringify(body) },
  );
// The Workspace's workflows, as the web composer lists them ("Other workflow…").
export const loadWorkflowCatalog = (projectId: string) =>
  api<{ workflows?: WorkflowOption[] }>(
    `/chat/api/workflows${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`,
  );
export const decideChatApproval = (approvalId: string, decision: "approve" | "reject") =>
  api<unknown>(`/chat/api/approvals/${encodeURIComponent(approvalId)}/${decision}`, { method: "POST" });

// Approvals on the go (backend): the pending approvals this person may decide, and Allow once or Deny with an
// optional reason. "Always for this Workspace" is not a phone route.
export const loadDecidableApprovals = () => api<unknown>("/api/v1/approvals/decidable");

export const decideApproval = (approvalId: string, decision: "approve" | "reject", reason = "") =>
  api<unknown>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/${decision}`, {
    method: "POST",
    body: JSON.stringify(reason.trim() ? { reason: reason.trim() } : {}),
  });
