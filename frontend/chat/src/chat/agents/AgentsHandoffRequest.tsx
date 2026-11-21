import { useEffect, useState } from "react";

import { loadClaims, requestHandoff } from "./agentBoardApi";
import { loadAgentPresence } from "./agentPresenceApi";
import { readPresence } from "./agentPresenceModel";
import { boardActionErrorText, readClaims } from "./agentBoardModel";
import type { BoardUser, BoardWorkItem } from "./agentBoardTypes";

const BODY_LIMIT = 8000;

// "Request handoff to…" (admins): posts a `handoff_request` with author type human to a chosen user's
// agent. The choices are the Workspace's known work items (board and active claims) and the users with a connected
// agent client; nothing is free-typed. The server authorizes the request and secret-scans the text.
export function AgentsHandoffRequest({ projectId, workItems, onPosted, onClose }: {
  projectId: string;
  workItems: BoardWorkItem[];
  onPosted: () => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<BoardWorkItem[]>(workItems);
  const [users, setUsers] = useState<BoardUser[]>([]);
  const [workItemId, setWorkItemId] = useState("");
  const [userId, setUserId] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadClaims(projectId).then((payload) => {
      if (!current) return;
      const claimed = (readClaims(payload) ?? []).map((claim) => claim.workItem).filter((item): item is BoardWorkItem => item !== null);
      setItems((known) => uniqueBy([...known, ...claimed], (item) => item.id));
    }).catch(() => undefined);
    loadAgentPresence(projectId).then((payload) => {
      if (!current) return;
      const clients = readPresence(payload) ?? [];
      setUsers(uniqueBy(clients.filter((client) => client.userId).map((client) => ({ id: client.userId, name: client.user })), (user) => user.id));
    }).catch(() => undefined);
    return () => { current = false; };
  }, [projectId]);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await requestHandoff({ project_id: projectId, work_item_id: workItemId, to_user_id: userId, body: body.trim() });
      onPosted();
      onClose();
    } catch (error) {
      setProblem(boardActionErrorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="admin-panel__card agents-board" aria-label="Request a handoff" data-testid="agents-handoff-form">
      <div className="admin-panel__section-header"><h2 className="agents-area__section-title">Request a handoff to another user's agent</h2></div>
      <div className="agents-handoff-policy__grid">
        <label className="admin-panel__field"><span>Work item</span>
          <select value={workItemId} onChange={(event) => setWorkItemId(event.target.value)}>
            <option value="">Choose a work item</option>
            {items.map((item) => <option key={item.id} value={item.id}>{[item.key, item.title].filter(Boolean).join(" – ")}</option>)}
          </select>
        </label>
        <label className="admin-panel__field"><span>To the agent of</span>
          <select value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">Choose a user</option>
            {users.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}
          </select>
        </label>
      </div>
      {!users.length ? <p className="agents-area__hint">Only users with a connected agent client can be chosen.</p> : null}
      <label className="admin-panel__field"><span>Handoff note</span>
        <textarea rows={4} maxLength={BODY_LIMIT} value={body}
          placeholder="What should the receiving agent know? No secrets." onChange={(event) => setBody(event.target.value)} />
      </label>
      <div className="agents-board__actions agents-board__actions--end">
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !workItemId || !userId || !body.trim()}
          onClick={() => void submit()}>Post handoff request</button>
      </div>
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-handoff-error">{problem}</p> : null}
    </section>
  );
}

function uniqueBy<T>(entries: T[], key: (entry: T) => string): T[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    const id = key(entry);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}
