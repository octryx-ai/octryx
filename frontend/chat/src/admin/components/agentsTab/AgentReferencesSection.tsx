import {
  NO_REFERENCES_TEXT,
  TRUNCATED_TEXT,
  agentReferenceGroups,
  type AgentReferenceRow,
  type AgentReferencesPayload,
} from "./agentReferencesModel";
import { useAgentReferences, type AgentReferencesState } from "./useAgentReferences";

type ViewProps = { state: AgentReferencesState; payload: AgentReferencesPayload | null };

function ReferenceTable({ id, title, rows, emptyText }: {
  id: string; title: string; rows: AgentReferenceRow[]; emptyText: string;
}) {
  return (
    <div className="agent-references__group">
      <h4 id={id}>{title}</h4>
      {rows.length === 0 ? (
        <p className="agent-workspace__hint">{emptyText}</p>
      ) : (
        <table className="admin-panel__table agent-references__table" aria-labelledby={id}>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Workspace</th>
              <th scope="col">Uses this agent in</th>
              <th scope="col">Link opens</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td><a href={row.href} aria-label={row.linkLabel}>{row.name}</a></td>
                <td>{row.workspace}</td>
                <td>{row.state}</td>
                <td>{row.destination}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// "Used by": workflows the caller can see that reference this agent,
// each linked to its editor. Never a global total.
export function AgentReferencesView({ state, payload }: ViewProps) {
  const groups = agentReferenceGroups(payload);
  return (
    <section className="agent-workspace__section" aria-labelledby="agent-workspace-references">
      <h3 id="agent-workspace-references">Used by</h3>
      <p className="agent-workspace__hint">
        Workflows you can see that reference this agent. Each link opens the editor at the
        latest version, which may differ from the version that uses the agent.
      </p>
      {state === "loading" ? (
        <p className="agent-workspace__hint" role="status">Reading where this agent is used…</p>
      ) : state === "error" ? (
        <p className="admin-panel__form-error" role="alert">Could not read where this agent is used. Try again later.</p>
      ) : groups.empty ? (
        <p className="admin-panel__empty-state">{NO_REFERENCES_TEXT}</p>
      ) : (
        <ReferenceTable id="agent-references-workflows" title="Workflows" rows={groups.workflows}
          emptyText="No workflow you can see uses this agent." />
      )}
      {state === "ready" && groups.truncated ? (
        <p className="agent-workspace__hint" role="note">{TRUNCATED_TEXT}</p>
      ) : null}
    </section>
  );
}

export function AgentReferencesSection({ agentId }: { agentId: string }) {
  const { state, payload } = useAgentReferences(agentId);
  return <AgentReferencesView state={state} payload={payload} />;
}
