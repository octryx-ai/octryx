import type { WorkCodingObservability, WorkCodingObservabilityEvent } from "./codingTypes";

export function RuntimeObservabilitySummary({ observability }: { observability: WorkCodingObservability | null }) {
  if (!observability) {
    return (
      <section className="coding-runtime-observability is-empty">
        <div>
          <div className="work-area__eyebrow">Runtime observability</div>
          <h3>No runtime cost evidence yet</h3>
          <p>Start a governed coding agent run to capture model usage, tool calls, stop reasons, and audit events.</p>
        </div>
      </section>
    );
  }
  const summary = observability.summary;
  const topTools = observability.tools.by_name.slice(0, 4);
  return (
    <section className={`coding-runtime-observability is-${summary.status}`}>
      <div className="coding-runtime-observability__header">
        <div>
          <div className="work-area__eyebrow">Runtime observability</div>
          <h3>{summary.next_observation}</h3>
        </div>
        <span className={`work-badge work-badge--${summary.status === "attention" ? "attention" : "neutral"}`}>
          {summary.status.replaceAll("_", " ")}
        </span>
      </div>
      <div className="coding-runtime-observability__metrics">
        <RuntimeKeyValue label="Cost" value={`$${summary.total_cost}`} />
        <RuntimeKeyValue label="Tokens" value={formatNumber(summary.total_tokens)} />
        <RuntimeKeyValue label="LLM calls" value={String(summary.llm_call_count)} />
        <RuntimeKeyValue label="Tool calls" value={String(summary.tool_call_count)} />
        <RuntimeKeyValue label="Failed tools" value={String(summary.failed_tool_call_count)} />
        <RuntimeKeyValue label="Repeated calls" value={String(summary.repeated_tool_call_count)} />
      </div>
      {summary.latest_stop_reason ? (
        <p className="coding-detail__warning">Latest stop: {summary.latest_stop_reason}</p>
      ) : null}
      {topTools.length ? (
        <div className="coding-runtime-observability__tools">
          {topTools.map((tool) => (
            <span key={tool.tool_name} className="work-badge">
              {tool.tool_name}: {tool.count}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function RuntimeObservabilityDeepDive({ observability }: { observability: WorkCodingObservability | null }) {
  if (!observability) {
    return (
      <section className="coding-detail__evidence">
        <h3>Runtime observability</h3>
        <p className="work-detail__empty">No runtime events are linked to this Work Item yet.</p>
      </section>
    );
  }
  return (
    <section className="coding-detail__evidence">
      <h3>Runtime observability</h3>
      <div className="coding-detail__metrics">
        <RuntimeKeyValue label="Sessions" value={String(observability.summary.agent_session_count)} />
        <RuntimeKeyValue label="Cost" value={`$${observability.summary.total_cost}`} />
        <RuntimeKeyValue label="Tokens in" value={formatNumber(observability.usage.total.tokens_in)} />
        <RuntimeKeyValue label="Tokens out" value={formatNumber(observability.usage.total.tokens_out)} />
        <RuntimeKeyValue
          label="Audit events"
          value={String(observability.summary.coding_audit_event_count + observability.summary.platform_audit_event_count)}
        />
        <RuntimeKeyValue label="Stop reason" value={observability.summary.latest_stop_reason || "Not captured"} />
      </div>
      <div className="coding-runtime-observability__columns">
        <RuntimeBucketList
          title="Model usage"
          rows={observability.usage.by_model.map((row) => ({
            key: row.key,
            meta: `${formatNumber(row.tokens_total)} tokens · $${row.cost}`,
            status: `${row.events} calls`,
          }))}
        />
        <RuntimeBucketList
          title="Tool calls"
          rows={observability.tools.by_name.slice(0, 8).map((row) => ({
            key: row.tool_name,
            meta: `${row.kind} · ${row.success} ok · ${row.failed} failed`,
            status: `${row.count}`,
          }))}
        />
        <RuntimeBucketList
          title="Repeated calls"
          rows={observability.tools.repeated_calls.map((row) => ({
            key: row.tool_name,
            meta: JSON.stringify(row.parameters_preview),
            status: `${row.count}`,
          }))}
          emptyText="No repeated identical tool calls detected."
        />
      </div>
      <RuntimeTimeline events={observability.timeline.slice(-25)} />
    </section>
  );
}

function RuntimeBucketList({
  title,
  rows,
  emptyText = "No records.",
}: {
  title: string;
  rows: Array<{ key: string; meta: string; status: string }>;
  emptyText?: string;
}) {
  return (
    <div className="coding-runtime-bucket">
      <h4>{title}</h4>
      {rows.length === 0 ? <p className="work-detail__empty">{emptyText}</p> : null}
      {rows.map((row) => (
        <div key={`${title}-${row.key}-${row.meta}`} className="coding-runtime-bucket__row">
          <div>
            <strong>{row.key}</strong>
            <small>{row.meta}</small>
          </div>
          <span className="work-badge">{row.status}</span>
        </div>
      ))}
    </div>
  );
}

function RuntimeTimeline({ events }: { events: WorkCodingObservabilityEvent[] }) {
  if (events.length === 0) {
    return <p className="work-detail__empty">No runtime timeline events captured yet.</p>;
  }
  return (
    <ol className="coding-runtime-timeline">
      {events.map((event) => (
        <li key={`${event.kind}-${event.id}`}>
          <span className={`coding-runtime-timeline__dot is-${event.kind}`} />
          <div>
            <strong>{event.title}</strong>
            <small>{[event.kind, event.status, event.created_at].filter(Boolean).join(" · ")}</small>
            {event.summary ? <p>{event.summary}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function RuntimeKeyValue({ label, value }: { label: string; value: string }) {
  return (
    <dl className="coding-detail__kv">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </dl>
  );
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}
