import { readJson } from "../../admin/utils/adminPanelHelpers";
import { quietHoursBody, readQuietHours } from "./companionModel";
import { readAttention } from "./companionRead";
import { type Attention, type AttentionRequest, type QuietHours } from "./companionTypes";
import { emergencyStopRequest, handoverRequest, readCandidates, type HandoverCandidate } from "./companionHandoverModel";
import { abortRequest, jobPath, jobsPath, readJobDetail, readJobs, type Job, type JobDetail, type JobScope } from "./companionJobModel";
import { prefetch, takePrefetched } from "../startupPrefetch";

// The companion's requests. Refusals keep their message and HTTP status on the error (readJson), so the panel can
// show the server's own words in place.

export const ATTENTION_PATH = "/api/v1/attention";
export const ATTENTION_WS_PATH = "/api/v1/attention/ws";
const PREFERENCES_PATH = "/api/v1/notifications/preferences";

/** The attention payload; a refusal keeps the server's message and status. */
export async function loadAttention(): Promise<Attention> {
  const attention = readAttention(await (takePrefetched<unknown>(ATTENTION_PATH) ?? readJson<unknown>(ATTENTION_PATH)));
  if (!attention) throw Object.assign(new Error("The server's answer was not an attention list."), { status: 0 });
  return attention;
}

/** Starts the first attention read with the bundle, before the shell that shows it has mounted. */
export function prefetchAttention(): void {
  prefetch(ATTENTION_PATH, () => readJson<unknown>(ATTENTION_PATH));
}

export function sendAttentionAction(request: AttentionRequest): Promise<unknown> {
  return readJson<unknown>(request.path, { method: request.method, body: JSON.stringify(request.body) });
}

export async function loadQuietHours(): Promise<{ quiet: QuietHours; stored: boolean; preferences: unknown }> {
  const preferences = await readJson<unknown>(PREFERENCES_PATH);
  return { ...readQuietHours(preferences), preferences };
}

/** Saves quiet hours (a partial update; the channel switches go along unchanged); `stored` is false when the server
 * ignored them. */
export async function saveQuietHours(preferences: unknown, quiet: QuietHours): Promise<{ quiet: QuietHours; stored: boolean; preferences: unknown }> {
  const saved = await readJson<unknown>(PREFERENCES_PATH, { method: "PUT", body: JSON.stringify(quietHoursBody(preferences, quiet)) });
  const read = readQuietHours(saved);
  return { quiet: read.stored ? read.quiet : quiet, stored: read.stored, preferences: saved };
}

const notAJob = () => Object.assign(new Error("The server's answer was not a job."), { status: 0 });

export async function loadJobs(scope: JobScope, workspaceId: string): Promise<Job[]> {
  const jobs = readJobs(await readJson<unknown>(jobsPath(scope, workspaceId)));
  if (!jobs) throw notAJob();
  return jobs;
}

export async function loadJob(runId: string): Promise<JobDetail> {
  const job = readJobDetail(await readJson<unknown>(jobPath(runId)));
  if (!job) throw notAJob();
  return job;
}

/** Aborts a run through the run's own action endpoint; the reason is required and recorded. */
export function abortJob(runId: string, reason: string): Promise<unknown> {
  const request = abortRequest(runId, reason);
  return readJson<unknown>(request.path, { method: "POST", body: JSON.stringify(request.body) });
}

/** Who a run can go to: the members of the run's Workspace. */
export async function loadHandoverCandidates(workspaceId: string, ownerId: string): Promise<HandoverCandidate[]> {
  if (!workspaceId) return [];
  return readCandidates(await readJson<unknown>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/members`), ownerId);
}

export function requestHandover(runId: string, toUserId: string, reason: string): Promise<unknown> {
  const request = handoverRequest(runId, toUserId, reason);
  if ("error" in request) return Promise.reject(Object.assign(new Error(request.error), { status: 0 }));
  return readJson<unknown>(request.path, { method: "POST", body: JSON.stringify(request.body) });
}

/** An admin's emergency stop: also stops the run's device job, with an audit row (the server's part). */
export function emergencyStop(runId: string, reason: string): Promise<unknown> {
  const request = emergencyStopRequest(runId, reason);
  return readJson<unknown>(request.path, { method: "POST", body: JSON.stringify(request.body) });
}

/** ws(s)://host/api/v1/attention/ws — authenticated by the session cookie, so no token in the URL. */
export function attentionSocketUrl(location: Pick<Location, "protocol" | "host">): string {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${ATTENTION_WS_PATH}`;
}
