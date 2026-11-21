import { useEffect, useState } from "react";

import { loadDeviceJobs } from "../devices/deviceJobsApi";
import { readJobs } from "../devices/deviceJobsModel";
import { type DeviceJob } from "../devices/deviceJobTypes";
import { listTranscripts } from "./transcriptApi";
import { readTranscriptList, transcriptFilterQuery, type TranscriptFilter, type TranscriptItem } from "./transcriptModel";

// Whether a session, run or device job has a stored transcript. Each answer is kept a minute per query, so the
// header and a panel of the same page ask once.
const KEEP_MS = 60_000;
const cache = new Map<string, { at: number; value: Promise<unknown> }>();

function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < KEEP_MS) return hit.value as Promise<T>;
  const value = load();
  cache.set(key, { at: Date.now(), value });
  return value;
}

function lookup(projectId: string, filter: TranscriptFilter): Promise<TranscriptItem[]> {
  // A refusal (404 for a non-member, a server without the route) means: no transcript to offer.
  return cached(`list:${projectId}?${transcriptFilterQuery(filter)}`, () =>
    listTranscripts(projectId, filter).then((payload) => readTranscriptList(payload) ?? []).catch(() => []));
}

/** One list, newest first, each session once. */
export function mergeItems(lists: TranscriptItem[][]): TranscriptItem[] {
  const seen = new Set<string>();
  const merged = lists.flat().filter((item) => (seen.has(item.sessionId) ? false : (seen.add(item.sessionId), true)));
  return merged.sort((a, b) => String(b.lastAt ?? "").localeCompare(String(a.lastAt ?? "")));
}

/**
 * The transcripts matching any of the filters; [] while loading, without a Workspace or filter, or on a refusal.
 * `filters` is compared by its query strings, so callers may pass a new array on every render.
 */
export function useTranscriptItems(projectId: string | null | undefined, filters: TranscriptFilter[]): TranscriptItem[] {
  const queries = filters.map(transcriptFilterQuery).filter(Boolean);
  const key = projectId && queries.length ? `${projectId}?${queries.join("&&")}` : "";
  const [found, setFound] = useState<{ key: string; items: TranscriptItem[] }>({ key: "", items: [] });
  useEffect(() => {
    if (!key || !projectId) return undefined;
    let current = true;
    const wanted = filters.filter((filter) => transcriptFilterQuery(filter));
    void Promise.all(wanted.map((filter) => lookup(projectId, filter))).then((lists) => {
      if (current) setFound({ key, items: mergeItems(lists) });
    });
    return () => { current = false; };
    // `key` stands for the project and every filter's values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return key && found.key === key ? found.items : [];
}

// A thread can run several device jobs; the newest few are offered.
const DEVICE_JOBS_ASKED = 3;

/** A thread's device jobs, oldest first; [] when `enabled` is false or the thread has none. Kept a minute, so the
 * header's engine badge and the transcript entry ask once. */
export function useThreadDeviceJobs(sessionId: string | null | undefined, enabled: boolean): DeviceJob[] {
  const [jobs, setJobs] = useState<{ key: string; jobs: DeviceJob[] }>({ key: "", jobs: [] });
  const key = enabled && sessionId ? sessionId : "";
  useEffect(() => {
    if (!key) return undefined;
    let current = true;
    void cached(`jobs:${key}`, () => loadDeviceJobs(key).then((payload) => readJobs(payload) ?? []).catch(() => []))
      .then((list) => {
        if (current) setJobs({ key, jobs: list });
      });
    return () => { current = false; };
  }, [key]);
  return key && jobs.key === key ? jobs.jobs : NO_JOBS;
}

const NO_JOBS: DeviceJob[] = [];

/** The ids of a thread's newest device jobs; [] when `enabled` is false or the thread has none. */
export function useThreadDeviceJobIds(sessionId: string | null | undefined, enabled: boolean): string[] {
  return useThreadDeviceJobs(sessionId, enabled).slice(-DEVICE_JOBS_ASKED).reverse().map((job) => job.id);
}
