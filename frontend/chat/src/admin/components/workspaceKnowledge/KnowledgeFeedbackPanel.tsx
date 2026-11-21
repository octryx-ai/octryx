import { useCallback, useEffect, useState } from "react";
import { FEEDBACK_ASPECTS, feedbackApi } from "./feedbackApi";
import type { AnswerFeedbackItem, AnswerFeedbackSummary, FeedbackAspect, FeedbackFilters, FeedbackRating } from "./feedbackApi";

const ASPECT_LABEL: Record<FeedbackAspect, string> = {
  correctness: "Correctness",
  sources: "Sources",
  completeness: "Completeness",
  clarity: "Clarity",
  tool_use: "Tool use",
  speed: "Speed",
};
const NO_WORKFLOW = "(no workflow)";

function AspectMarks({ item }: { item: AnswerFeedbackItem }) {
  const entries = Object.entries(item.aspects) as Array<[FeedbackAspect, "liked" | "disliked"]>;
  if (!entries.length) return <span className="admin-panel__muted">–</span>;
  return (
    <>
      {entries.map(([aspect, verdict]) => (
        <span key={aspect} style={{ marginRight: "0.3rem" }}
          className={`admin-panel__badge ${verdict === "liked" ? "admin-panel__badge--active" : "admin-panel__badge--danger"}`}>
          {verdict === "liked" ? "+" : "−"} {ASPECT_LABEL[aspect] ?? aspect}
        </span>
      ))}
    </>
  );
}

function FeedbackText({ item }: { item: AnswerFeedbackItem }) {
  if (item.memory_state === "forgotten") {
    return <span className="admin-panel__muted">Forgotten: the texts were erased.</span>;
  }
  return (
    <>
      {item.liked ? <div style={{ whiteSpace: "pre-wrap" }}><strong>Good:</strong> {item.liked}</div> : null}
      {item.disliked ? <div style={{ whiteSpace: "pre-wrap" }}><strong>Not good:</strong> {item.disliked}</div> : null}
      {!item.liked && !item.disliked ? <span className="admin-panel__muted">No text</span> : null}
    </>
  );
}

// The learning surface of answer feedback (admin or owner only): whether answers were good or bad,
// what people liked and did not like, per workflow and aspect. Each row links to its session.
export function KnowledgeFeedbackPanel({ workspaceId }: { workspaceId: string }) {
  const [filters, setFilters] = useState<FeedbackFilters>({ rating: "", aspect: "", workflowKey: "" });
  const [items, setItems] = useState<AnswerFeedbackItem[] | null>(null);
  const [summary, setSummary] = useState<AnswerFeedbackSummary | null>(null);
  const [workflows, setWorkflows] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, counts] = await Promise.all([
        feedbackApi.list(workspaceId, filters),
        feedbackApi.summary(workspaceId, filters),
      ]);
      setItems(list.items);
      setSummary(counts);
      setWorkflows((known) => Array.from(new Set([
        ...known,
        ...counts.by_workflow.map((entry) => entry.workflow_key).filter((key): key is string => Boolean(key)),
      ])).sort());
      setMessage(null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }, [workspaceId, filters]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="admin-panel__stack">
      <div className="admin-panel__hint" style={{ margin: 0 }}>
        Answer feedback: people rate answers good or bad and say what was good and what was not. It is kept in this
        Workspace's memory, never injected into prompts; the agent recalls it only when asked for answer feedback.
      </div>
      <FeedbackFilterBar filters={filters} workflows={workflows} onFilters={setFilters} onRefresh={() => void load()} />
      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}

      {summary ? <FeedbackSummary summary={summary} /> : null}

      {items === null ? null : items.length ? (
        <FeedbackTable items={items} />
      ) : (
        <div className="admin-panel__hint" style={{ margin: 0 }}>No answer feedback matches these filters yet.</div>
      )}
    </div>
  );
}

function FeedbackFilterBar({ filters, workflows, onFilters, onRefresh }: {
  filters: FeedbackFilters;
  workflows: string[];
  onFilters: (next: FeedbackFilters) => void;
  onRefresh: () => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
      <select className="admin-panel__input" style={{ maxWidth: "10rem" }} aria-label="Rating" value={filters.rating}
        onChange={(event) => onFilters({ ...filters, rating: event.target.value as FeedbackRating | "" })}>
        <option value="">All ratings</option>
        <option value="good">Good</option>
        <option value="bad">Bad</option>
      </select>
      <select className="admin-panel__input" style={{ maxWidth: "12rem" }} aria-label="Aspect" value={filters.aspect}
        onChange={(event) => onFilters({ ...filters, aspect: event.target.value as FeedbackAspect | "" })}>
        <option value="">All aspects</option>
        {FEEDBACK_ASPECTS.map((aspect) => <option key={aspect} value={aspect}>{ASPECT_LABEL[aspect]}</option>)}
      </select>
      <select className="admin-panel__input" style={{ maxWidth: "16rem" }} aria-label="Workflow"
        value={filters.workflowKey} onChange={(event) => onFilters({ ...filters, workflowKey: event.target.value })}>
        <option value="">All workflows</option>
        {workflows.map((key) => <option key={key} value={key}>{key}</option>)}
      </select>
      <button type="button" className="admin-panel__action-btn" onClick={onRefresh}>Refresh</button>
    </div>
  );
}

function FeedbackSummary({ summary }: { summary: AnswerFeedbackSummary }) {
  return (
    <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
      <div className="admin-panel__table-wrap" style={{ flex: "1 1 18rem" }}>
        <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
          <thead><tr><th>Workflow</th><th>Good</th><th>Bad</th></tr></thead>
          <tbody>
            <tr><td><strong>All ({summary.total})</strong></td><td>{summary.good}</td><td>{summary.bad}</td></tr>
            {summary.by_workflow.map((entry) => (
              <tr key={entry.workflow_key ?? NO_WORKFLOW}>
                <td>{entry.workflow_key ?? <span className="admin-panel__muted">{NO_WORKFLOW}</span>}</td>
                <td>{entry.good}</td><td>{entry.bad}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="admin-panel__table-wrap" style={{ flex: "1 1 18rem" }}>
        <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
          <thead><tr><th>Aspect</th><th>Liked</th><th>Not liked</th></tr></thead>
          <tbody>
            {summary.by_aspect.map((entry) => (
              <tr key={entry.aspect}>
                <td>{ASPECT_LABEL[entry.aspect] ?? entry.aspect}</td><td>{entry.liked}</td><td>{entry.disliked}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FeedbackTable({ items }: { items: AnswerFeedbackItem[] }) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
        <thead><tr><th>Rating</th><th>Feedback</th><th>Aspects</th><th>Workflow</th><th>Answer</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <span className={`admin-panel__badge ${item.rating === "good" ? "admin-panel__badge--active" : "admin-panel__badge--danger"}`}>
                  {item.rating}
                </span>
              </td>
              <td style={{ minWidth: "16rem" }}><FeedbackText item={item} /></td>
              <td><AspectMarks item={item} /></td>
              <td className="admin-panel__muted">
                {item.workflow_key ?? NO_WORKFLOW}
                {item.execution_profile_id ? <div>{item.execution_profile_id}</div> : null}
              </td>
              <td className="admin-panel__muted">
                {item.session_link ? (
                  <a href={item.session_link} title={`Message ${item.message_id}`}>Open session</a>
                ) : null}
                <div>{[item.provider, item.model].filter(Boolean).join(" · ")}</div>
                <div>{[item.recorded_by, item.updated_at?.slice(0, 10)].filter(Boolean).join(" · ")}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
