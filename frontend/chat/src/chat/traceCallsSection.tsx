import { useState } from "react";

import type { TurnTrace, TurnTraceCall } from "../chatThreadTypes";
import { callFacts, callTime, callsHeading, deviceNote, traceCalls } from "./traceCallsModel";
import { TraceValue } from "./traceUiComponents";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "done"; trace: TurnTrace };

// One call: its facts in one line; "Show" loads what was sent and what came back (the stored, redacted content).
function CallRow({ call, index, current, loadTrace }: {
  call: TurnTraceCall;
  index: number;
  current: TurnTrace;
  loadTrace?: (traceId: string) => Promise<TurnTrace | null>;
}) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState<Loaded | null>(call.id === current.id ? { state: "done", trace: current } : null);
  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || loaded?.state === "done" || loaded?.state === "loading" || !loadTrace) return;
    setLoaded({ state: "loading" });
    const trace = await loadTrace(call.id).catch(() => null);
    setLoaded(trace ? { state: "done", trace } : { state: "failed" });
  };
  const canOpen = Boolean(loadTrace) || loaded?.state === "done";
  return (
    <li className="trace-calls__row" data-testid="trace-call">
      <div className="trace-calls__line">
        <span className="trace-calls__index">{index + 1}</span>
        <span className="trace-calls__time">{callTime(call.createdAt)}</span>
        <span className="trace-calls__model">{call.model || call.provider}</span>
        <span className="trace-calls__facts">{callFacts(call)}</span>
        {canOpen ? (
          <button type="button" className="admin-panel__action-btn" aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} call ${index + 1}`} onClick={() => void toggle()}>
            {open ? "Hide" : "Show"}
          </button>
        ) : null}
      </div>
      {open ? (
        <div className="trace-calls__detail">
          {loaded?.state === "loading" ? <p className="trace-calls__note" role="status">Loading the call…</p> : null}
          {loaded?.state === "failed" ? <p className="trace-calls__error" role="alert">The call could not be loaded.</p> : null}
          {loaded?.state === "done" ? (
            <>
              <h5>Sent</h5>
              <TraceValue value={loaded.trace.inputMessages} />
              <h5>Received</h5>
              <TraceValue value={loaded.trace.rawOutput} />
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

// The answer's model calls (seat and API gateway turns, device turns that sent their calls through the platform),
// or the honest note that a device turn's prompt never reached the platform.
export function TraceCallsSection({ trace, loadTrace }: {
  trace: TurnTrace;
  loadTrace?: (traceId: string) => Promise<TurnTrace | null>;
}) {
  const calls = traceCalls(trace);
  const note = deviceNote(trace);
  if (!calls.length && !note) return null;
  return (
    <section className="turn-trace-section trace-calls" data-testid="trace-calls">
      <h4>{calls.length ? callsHeading(calls) : "Model calls"}</h4>
      {note ? <p className="trace-calls__note" data-testid="trace-device-note">{note}</p> : null}
      {calls.length ? (
        <ol className="trace-calls__list">
          {calls.map((call, index) => (
            <CallRow key={call.id} call={call} index={index} current={trace} loadTrace={loadTrace} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}
