import { useEffect, useState } from "react";
import { buildChatSearch } from "../../chat/appHelpers";
import "./adminChannels.css";

type CallSession = {
  id: string;
  call_id: string;
  channel_id: string;
  project_id: string | null;
  project_name: string;
  status: string;
  turns: number;
  message_count: number;
  last_error: string | null;
  stt_provider: string | null;
  started_at: string | null;
  ended_at: string | null;
  last_activity_at: string | null;
};

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatDuration(started: string | null, ended: string | null): string {
  if (!started) return "—";
  const end = ended ? new Date(ended).getTime() : Date.now();
  const secs = Math.floor((end - new Date(started).getTime()) / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function statusBadge(status: string, lastError: string | null) {
  if (lastError) {
    return (
      <span
        className="admin-panel__badge admin-panel__badge--inactive"
        title={lastError}
      >
        failed
      </span>
    );
  }
  const cls =
    status === "active"
      ? "admin-panel__badge--active"
      : status === "completed"
        ? "admin-panel__badge--success"
        : "admin-panel__badge--inactive";
  return <span className={`admin-panel__badge ${cls}`}>{status}</span>;
}

type AdminCallSessionsSectionProps = {
  /** Whether a Microsoft Teams channel is configured. */
  teamsConfigured: boolean;
  onSetUpChannel: () => void;
};

function CallSessionRow({ s }: { s: CallSession }) {
  return (
    <tr>
      <td>
        <code style={{ fontSize: "var(--ds-text-xs)" }}>
          {s.call_id
            ? s.call_id.slice(0, 16) + "…"
            : s.id.slice(0, 16) + "…"}
        </code>
        {s.last_error ? (
          <div
            className="admin-panel__cell--muted"
            style={{
              color: "var(--color-danger, #e55)",
              fontSize: "var(--ds-text-xs)",
              maxWidth: 220,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={s.last_error}
          >
            {s.last_error}
          </div>
        ) : null}
      </td>
      <td className="admin-panel__cell--muted">
        {s.project_name || "—"}
      </td>
      <td>{statusBadge(s.status, s.last_error)}</td>
      <td className="admin-panel__cell--muted">{s.turns}</td>
      <td className="admin-panel__cell--muted">
        {formatDuration(s.started_at, s.ended_at)}
      </td>
      <td className="admin-panel__cell--muted">
        {formatRelativeTime(s.started_at)}
      </td>
      <td>
        <a
          className="admin-panel__action-btn"
          href={`/chat${buildChatSearch({ sessionId: s.id })}`}
        >
          Transcript
        </a>
      </td>
    </tr>
  );
}

function CallSessionsTable({ sessions }: { sessions: CallSession[] }) {
  return (
    <table className="admin-panel__table">
      <thead>
        <tr>
          <th>Call ID</th>
          <th>Project</th>
          <th>Status</th>
          <th>Turns</th>
          <th>Duration</th>
          <th>Started</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <CallSessionRow key={s.id} s={s} />
        ))}
      </tbody>
    </table>
  );
}

function CallSessionsEmpty({ teamsConfigured, onSetUpChannel }: AdminCallSessionsSectionProps) {
  return (
    <div className="admin-panel__empty">
      {teamsConfigured
        ? "No call sessions yet."
        : "Call sessions need a configured Microsoft Teams channel."}
      {teamsConfigured ? null : (
        <div className="admin-channels__empty-action">
          <button type="button" className="admin-panel__action-btn" onClick={onSetUpChannel}>
            Set up a channel
          </button>
        </div>
      )}
    </div>
  );
}

export function AdminCallSessionsSection({
  teamsConfigured,
  onSetUpChannel,
}: AdminCallSessionsSectionProps) {
  const [sessions, setSessions] = useState<CallSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/admin/chat/api/panel/call-sessions?limit=50");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setSessions((await resp.json()) as CallSession[]);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div style={{ marginTop: "2rem" }}>
      <div className="admin-panel__section-header">
        <span className="admin-panel__section-title">Teams call sessions</span>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error ? (
        <div className="admin-panel__error">{error}</div>
      ) : sessions.length === 0 && !loading ? (
        <CallSessionsEmpty teamsConfigured={teamsConfigured} onSetUpChannel={onSetUpChannel} />
      ) : (
        <CallSessionsTable sessions={sessions} />
      )}
    </div>
  );
}
