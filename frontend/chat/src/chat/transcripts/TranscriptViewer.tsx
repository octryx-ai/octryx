import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { formatDateTime } from "../../admin/utils/dateTime";
import { SidePanel } from "../../layout/SidePanel";
import { loadTranscriptPage } from "./transcriptApi";
import { appendPage, initialPaging, MAIN_STREAM, nextRequest, orderStreams, pagingFailed, readTranscriptPage, streamLabel, type StreamPaging, type TranscriptItem, type TranscriptStream } from "./transcriptModel";
import { entryItems, formatBytes } from "./transcriptEntryItems";
import { TranscriptBlock } from "./TranscriptBlock";
import "./transcripts.css";

// The full Claude Code transcript of an octryx-claude session (Workspace switch): one tab per stream
// (Main, then each subagent), one page of lines at a time. Nothing is read before a tab is opened and every
// further page is asked for by the reader, because each read is audited.

function sessionOptionLabel(item: TranscriptItem): string {
  const when = item.firstAt ? formatDateTime(item.firstAt, "") : "";
  return [when, item.deviceJobId ? `job ${item.deviceJobId}` : ""].filter(Boolean).join(" · ") || item.sessionId;
}

function subtitle(item: TranscriptItem, stream: TranscriptStream | undefined): string {
  const first = item.firstAt ? formatDateTime(item.firstAt, "") : "";
  const last = item.lastAt ? formatDateTime(item.lastAt, "") : "";
  const range = first && last && first !== last ? `${first} – ${last}` : first || last;
  return [range, stream ? `${stream.lines} lines` : "", `${formatBytes(item.bytesStored)} stored`].filter(Boolean).join(" · ");
}

function StreamView({ sessionId, stream }: { sessionId: string; stream: TranscriptStream }) {
  const [paging, setPaging] = useState<StreamPaging>(() => initialPaging(stream.firstLine || 1));
  const pagingRef = useRef(paging);
  pagingRef.current = paging;
  // One request at a time, also before the "loading" state has rendered (every read is audited).
  const inFlight = useRef(false);

  const loadMore = useCallback(async () => {
    const request = nextRequest(pagingRef.current);
    if (!request || inFlight.current) return;
    inFlight.current = true;
    setPaging((current) => ({ ...current, loading: true }));
    try {
      const page = readTranscriptPage(await loadTranscriptPage(sessionId, stream.stream, request.fromLine, request.limit));
      setPaging((current) => (page ? appendPage(current, page) : pagingFailed(current, undefined)));
    } catch (error) {
      setPaging((current) => pagingFailed(current, (error as { status?: number }).status));
    } finally {
      inFlight.current = false;
    }
  }, [sessionId, stream.stream]);

  // The first page when the tab opens; a tab that was opened before keeps what it loaded (it stays mounted).
  useEffect(() => { void loadMore(); }, [loadMore]);

  const items = useMemo(() => paging.lines.flatMap((entry) => entryItems(entry.line, entry.entry)), [paging.lines]);

  if (paging.problem === "missing") {
    return <p className="admin-panel__empty-state" data-testid="transcript-missing">No transcript, or you can't read it.</p>;
  }
  return (
    <div className="transcript-stream" data-testid={`transcript-stream-${stream.stream}`}>
      {items.length === 0 && paging.loading ? <p className="transcript-stream__hint" role="status">Loading the transcript…</p> : null}
      {items.length === 0 && !paging.loading && paging.next === null && !paging.problem
        ? <p className="admin-panel__empty-state">This stream has no lines.</p> : null}
      <div className="transcript-stream__lines">
        {items.map((item) => <TranscriptBlock key={item.key} item={item} />)}
      </div>
      {paging.problem === "failed" ? <p className="work-area__error" role="alert">The next lines could not be loaded.</p> : null}
      {paging.next !== null && (items.length > 0 || paging.problem === "failed") ? (
        <div className="transcript-stream__more">
          <span className="transcript-stream__hint">
            {paging.lines.length} of {stream.lines} lines shown
          </span>
          <button type="button" className="admin-panel__action-btn" disabled={paging.loading} data-testid="transcript-load-more"
            onClick={() => void loadMore()}>
            {paging.loading ? "Loading…" : paging.problem === "failed" ? "Try again" : "Load more"}
          </button>
        </div>
      ) : null}
      {paging.next === null && items.length > 0 ? <p className="transcript-stream__hint transcript-stream__end">End of the transcript.</p> : null}
    </div>
  );
}

export function TranscriptViewer({ items, onClose }: { items: TranscriptItem[]; onClose: () => void }) {
  const [sessionId, setSessionId] = useState(items[0]?.sessionId ?? "");
  const item = items.find((entry) => entry.sessionId === sessionId) ?? items[0];
  const streams = useMemo(() => orderStreams(item?.streams ?? []), [item]);
  const [active, setActive] = useState(MAIN_STREAM);
  // Tabs opened once stay mounted (hidden), so switching back does not read the same lines again.
  const [opened, setOpened] = useState<string[]>([]);
  const current = streams.find((entry) => entry.stream === active) ?? streams[0];

  useEffect(() => {
    if (current && !opened.includes(current.stream)) setOpened((list) => [...list, current.stream]);
  }, [current, opened]);

  if (!item || typeof document === "undefined") return null;
  const chooseSession = (next: string) => {
    setSessionId(next);
    setActive(MAIN_STREAM);
    setOpened([]);
  };

  return createPortal(
    <div className="transcript-layer">
      <SidePanel
        title="Session transcript"
        subtitle={subtitle(item, current)}
        onClose={onClose}
        testId="transcript-panel"
        tabs={streams.length > 1 ? {
          label: "Transcript streams",
          idPrefix: "transcript",
          value: current?.stream ?? MAIN_STREAM,
          onChange: setActive,
          tabs: streams.map((entry) => ({ key: entry.stream, label: streamLabel(entry.stream), count: entry.lines })),
        } : undefined}
      >
        {items.length > 1 ? (
          <label className="admin-panel__field transcript-session-pick">
            <span>Session</span>
            <select value={item.sessionId} onChange={(event) => chooseSession(event.target.value)} aria-label="Session">
              {items.map((entry) => <option key={entry.sessionId} value={entry.sessionId}>{sessionOptionLabel(entry)}</option>)}
            </select>
          </label>
        ) : null}
        <p className="transcript-note">Secrets are redacted. Every page you open here is recorded in the audit log.</p>
        {streams.length === 0 ? <p className="admin-panel__empty-state">No transcript, or you can't read it.</p> : null}
        {opened.map((stream) => {
          const entry = streams.find((candidate) => candidate.stream === stream);
          return entry ? (
            <div key={`${item.sessionId}-${stream}`} hidden={stream !== current?.stream}>
              <StreamView sessionId={item.sessionId} stream={entry} />
            </div>
          ) : null;
        })}
      </SidePanel>
    </div>,
    document.body,
  );
}
