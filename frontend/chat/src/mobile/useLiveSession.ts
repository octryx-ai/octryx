// The live session's data: its messages and progress polled from the Mac, the composer state and open steps.

import { useCallback, useEffect, useRef, useState } from "react";
import { loadLiveMessages, loadLiveProgress } from "./mobileApi";
import { liveStatusText, mergeProgress, readLiveProgress, type ProgressEvent } from "./mobileLiveProgress";
import { readLiveMessages, type LiveMessage, type LiveSession } from "./mobileLiveSessions";
import { useRefreshEvent } from "./pullToRefresh";
import type { Picture } from "./liveSessionText";
import { selecting } from "./mobileChatBrowser";
import { loadOpen, saveOpen } from "./liveTimeline";

const POLL_MS = 3000;

export function useLiveSession(session: LiveSession) {
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [running, setRunning] = useState(session.fresh);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pictures, setPictures] = useState<Picture[]>([]);
  // What the session is doing: its steps, caught up from the last seq seen.
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [status, setStatus] = useState("");
  const [forking, setForking] = useState(false);
  const [allSteps, setAllSteps] = useState(false);
  const [openKeys, setOpenKeys] = useState<Set<string>>(() => loadOpen(session.peer));
  const toggle = (key: string) =>
    setOpenKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      saveOpen(session.peer, next);
      return next;
    });
  const lastSeq = useRef(0);
  const picker = useRef<HTMLInputElement | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const seen = useRef(0);

  const refresh = useCallback(async () => {
    if (selecting()) return;
    try {
      const data = readLiveMessages(
        await loadLiveMessages(session.deviceId, session.peer),
      );
      setMessages(data.items);
      setRunning(data.running);
    } catch {
      // the next poll tries again
    }
    try {
      const page = readLiveProgress(
        await loadLiveProgress(session.deviceId, session.peer, lastSeq.current),
      );
      if (page.events.length) {
        setProgress((current) => mergeProgress(current, page.events));
        lastSeq.current = page.events[page.events.length - 1].seq;
      }
      setStatus(liveStatusText(page.status, page.running));
    } catch {
      // progress is a view on top of the chat; the chat works without it
    }
  }, [session.deviceId, session.peer]);

  useRefreshEvent(refresh);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);
  return {
    messages, running, draft, setDraft, busy, setBusy, error, setError, pictures, setPictures, progress, status,
    forking, setForking, allSteps, setAllSteps, openKeys, toggle, picker, end, seen, refresh,
  };
}
