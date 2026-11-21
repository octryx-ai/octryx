import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { ProjectOption } from "../../../chatOptionTypes";
import { splitProducts } from "./workspaceKnowledgeRequest";
import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import type { BindingsOverview, KnowledgeBinding } from "./workspaceKnowledgeTypes";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { EmptyLine } from "../../../layout/EmptyLine";
import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";

const EFFECTIVE_BADGE: Record<KnowledgeBinding["effective"], string> = {
  active: "admin-panel__badge--active",
  inert: "admin-panel__badge--warning",
  revoked: "admin-panel__badge--inactive",
};
const INERT_TEXT: Record<string, string> = {
  classification_above_reader: "the source's data classification is now above this Workspace's",
  classification_unresolved: "a Workspace has no data classification",
  beyond_binding_limit: "beyond the maximum number of bindings",
};

function BindingTable({ rows, busy, canRevoke, onRevoke }: {
  rows: KnowledgeBinding[];
  busy: boolean;
  canRevoke: boolean;
  onRevoke: (binding: KnowledgeBinding) => void;
}) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
        <thead><tr><th>Workspace</th><th>Products</th><th>State</th><th>Reason</th><th /></tr></thead>
        <tbody>
          {rows.map((binding) => (
            <tr key={binding.id}>
              <td>{binding.workspace_name || binding.workspace_id}</td>
              <td>{binding.products.join(", ") || "All"}</td>
              <td>
                <span className={`admin-panel__badge ${EFFECTIVE_BADGE[binding.effective]}`}>{binding.effective}</span>
                {binding.inert_reason ? (
                  <div className="admin-panel__muted">{INERT_TEXT[binding.inert_reason] ?? binding.inert_reason}</div>
                ) : null}
              </td>
              <td className="admin-panel__muted">{binding.reason || "—"}</td>
              <td>
                {canRevoke && binding.state === "active" ? (
                  <div className="admin-users__row-actions" style={{ justifyContent: "flex-end" }}>
                    <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy}
                      onClick={() => onRevoke(binding)}>Revoke</button>
                  </div>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Runs one bindings call: busy while it runs, then the new overview and the note, or the error as the message.
async function runBindingAction(action: () => Promise<BindingsOverview>, note: string | undefined, set: {
  setBusy: (busy: boolean) => void;
  setOverview: (overview: BindingsOverview) => void;
  setMessage: (message: string | null) => void;
}) {
  set.setBusy(true);
  try {
    set.setOverview(await action());
    set.setMessage(note ?? null);
  } catch (err) {
    set.setMessage(err instanceof Error ? err.message : String(err));
  } finally {
    set.setBusy(false);
  }
}

// Binds the source Workspace; the form is cleared once the server accepted it.
async function bindSource(workspaceId: string, form: { sourceId: string; products: string; reason: string }, clear: () => void) {
  const next = await workspaceKnowledgeApi.bind(workspaceId, {
    source_workspace_id: form.sourceId, products: splitProducts(form.products), reason: form.reason.trim(),
  });
  clear();
  return next;
}

// Which other Workspaces this Workspace reads (a shared library, the main brain), and who reads this one.
// Nothing is copied: each Workspace stays its own database, and search, changes and code impact read across.
// "Read another Workspace" is the page's primary action and opens a side panel; the rules of a binding
// are in the page help (help/knowledge/knowledgeBindings.md).
export function KnowledgeBindingsPanel({ workspaceId, projects }: { workspaceId: string; projects: ProjectOption[] }) {
  const [overview, setOverview] = useState<BindingsOverview | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [products, setProducts] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(
    (action: () => Promise<BindingsOverview>, note?: string) => runBindingAction(action, note, { setBusy, setOverview, setMessage }),
    [],
  );

  useEffect(() => {
    void run(() => workspaceKnowledgeApi.bindings(workspaceId));
  }, [run, workspaceId]);

  const bound = new Set((overview?.reads_from ?? []).filter((item) => item.state === "active").map((item) => item.workspace_id));
  const candidates = projects.filter((project) => project.id !== workspaceId && !bound.has(project.id));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!sourceId) return;
    void run(() => bindSource(workspaceId, { sourceId, products, reason }, () => {
      setSourceId("");
      setProducts("");
      setReason("");
      setAdding(false);
    }), "Bound. Search, changes and code impact now read that Workspace too.");
  };

  if (!overview) return <div className="admin-panel__hint">{message ?? "Loading…"}</div>;
  const revoke = (binding: KnowledgeBinding) =>
    void run(() => workspaceKnowledgeApi.unbind(workspaceId, binding.id), `Revoked the binding to ${binding.workspace_name}.`);

  const close = () => setAdding(false);
  const open = () => { setMessage(null); setAdding(true); };
  return (
    <div className="admin-panel__stack">
      {overview.may_author ? (
        <AdminHeaderActions>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={open}
            data-testid="bindings-add">Read another Workspace</button>
        </AdminHeaderActions>
      ) : null}
      <ReadsFromSection overview={overview} busy={busy} onRevoke={revoke} onOpen={open} />

      {adding && overview.may_author ? (
        <BindingAddPanel candidates={candidates} message={message} busy={busy} sourceId={sourceId} products={products} reason={reason}
          onSourceId={setSourceId} onProducts={setProducts} onReason={setReason} onSubmit={submit} onClose={close} />
      ) : null}

      {message && !adding ? <div className="admin-panel__hint" role="status">{message}</div> : null}

      <ReadBySection overview={overview} busy={busy} onRevoke={revoke} />
    </div>
  );
}

// "Read another Workspace": the source Workspace, optional products and a reason; Bind submits the form.
function BindingAddPanel({ candidates, message, busy, sourceId, products, reason, onSourceId, onProducts, onReason, onSubmit, onClose }: {
  candidates: ProjectOption[];
  message: string | null;
  busy: boolean;
  sourceId: string;
  products: string;
  reason: string;
  onSourceId: (value: string) => void;
  onProducts: (value: string) => void;
  onReason: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
}) {
  return (
    <SidePanel title="Read another Workspace" onClose={onClose} testId="bindings-add-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="submit" form="knowledge-binding-form" className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={busy || !sourceId}>Bind</button>
        </>
      )}>
      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}
      <form id="knowledge-binding-form" onSubmit={onSubmit}>
        <FormSection title="Binding">
          <label className="admin-panel__field"><span>Source Workspace</span>
            <select className="admin-panel__input" value={sourceId} onChange={(event) => onSourceId(event.target.value)}>
              <option value="">Choose a Workspace…</option>
              {candidates.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
          <label className="admin-panel__field"><span>Products (optional)</span>
            <input className="admin-panel__input" placeholder="e.g. spring-boot" value={products}
              onChange={(event) => onProducts(event.target.value)} />
          </label>
          <label className="admin-panel__field"><span>Reason (optional)</span>
            <input className="admin-panel__input" value={reason} onChange={(event) => onReason(event.target.value)} />
          </label>
        </FormSection>
      </form>
    </SidePanel>
  );
}

type SectionProps = { overview: BindingsOverview; busy: boolean; onRevoke: (binding: KnowledgeBinding) => void };

function ReadsFromSection({ overview, busy, onRevoke, onOpen }: SectionProps & { onOpen: () => void }) {
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">This Workspace reads from ({overview.reads_from.length})</div>
      {overview.reads_from.length ? (
        <BindingTable rows={overview.reads_from} busy={busy} canRevoke={overview.may_author} onRevoke={onRevoke} />
      ) : (
        <EmptyLine text="This Workspace reads only its own knowledge."
          action={overview.may_author ? { label: "Read another Workspace", onClick: onOpen } : undefined}
          testId="bindings-empty" />
      )}
    </div>
  );
}

function ReadBySection({ overview, busy, onRevoke }: SectionProps) {
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Read by ({overview.read_by.length})</div>
      {overview.read_by.length ? (
        <BindingTable rows={overview.read_by} busy={busy} canRevoke={overview.may_author} onRevoke={onRevoke} />
      ) : (
        <div className="admin-panel__hint" style={{ margin: 0 }}>No other Workspace reads this one.</div>
      )}
    </div>
  );
}
