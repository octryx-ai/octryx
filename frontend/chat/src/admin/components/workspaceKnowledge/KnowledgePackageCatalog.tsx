import { useState } from "react";
import type { FormEvent } from "react";
import { PACKAGE_ROLES } from "./workspaceKnowledgeTypes";
import type { CatalogEntry, KnowledgePackage, PackageDocument } from "./workspaceKnowledgeTypes";

type Props = {
  pkg: KnowledgePackage;
  busy: boolean;
  onTrustSource: (pattern: string) => void;
  onDecide: (decisions: Record<string, "accepted" | "rejected">) => void;
  onAdd: (entry: CatalogEntry) => void;
  onEdit: (documentId: string, entry: CatalogEntry) => void;
  onRemove: (documentId: string) => void;
};

const EMPTY: CatalogEntry = { url: "", title: "", version: null, role: "reference" };

function EntryForm({ initial, label, busy, onSubmit, onCancel }: {
  initial: CatalogEntry;
  label: string;
  busy: boolean;
  onSubmit: (entry: CatalogEntry) => void;
  onCancel?: () => void;
}) {
  const [entry, setEntry] = useState<CatalogEntry>(initial);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ ...entry, version: entry.version?.trim() || null });
  };
  return (
    <form onSubmit={submit} style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1.4fr) minmax(0, 0.6fr) minmax(0, 1fr) auto auto", gap: "0.35rem" }}>
      <input className="admin-panel__input" placeholder="https://…" value={entry.url}
        onChange={(event) => setEntry({ ...entry, url: event.target.value })} />
      <input className="admin-panel__input" placeholder="Title" value={entry.title}
        onChange={(event) => setEntry({ ...entry, title: event.target.value })} />
      <input className="admin-panel__input" placeholder="Version" value={entry.version ?? ""}
        onChange={(event) => setEntry({ ...entry, version: event.target.value })} />
      <select className="admin-panel__input" value={entry.role}
        onChange={(event) => setEntry({ ...entry, role: event.target.value })}>
        {PACKAGE_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
      </select>
      <button type="submit" className="admin-panel__action-btn" disabled={busy || !entry.url || !entry.title}>{label}</button>
      {onCancel ? <button type="button" className="admin-panel__action-btn" onClick={onCancel}>Cancel</button> : <span />}
    </form>
  );
}

function SourceBadge({ document, busy, onTrustSource }: {
  document: PackageDocument;
  busy: boolean;
  onTrustSource: Props["onTrustSource"];
}) {
  if (document.source_state === "trusted") return null;
  if (document.source_state === "blocked") {
    return <div style={{ fontSize: "var(--ds-text-xs)" }}><strong>Blocked source</strong> — this document cannot be ingested.</div>;
  }
  return (
    <div style={{ fontSize: "var(--ds-text-xs)" }}>
      <strong>New source</strong> <code>{document.source_pattern ?? "?"}</code> is not trusted yet
      {document.source_pattern ? (
        <button type="button" className="admin-panel__action-btn" style={{ marginLeft: "0.4rem" }} disabled={busy}
          onClick={() => onTrustSource(document.source_pattern as string)}>Trust source</button>
      ) : null}
    </div>
  );
}

function DocumentRow({ document, busy, onTrustSource, onDecide, onEdit, onRemove }: {
  document: PackageDocument;
  busy: boolean;
  onTrustSource: Props["onTrustSource"];
  onDecide: Props["onDecide"];
  onEdit: Props["onEdit"];
  onRemove: Props["onRemove"];
}) {
  const [editing, setEditing] = useState(false);
  const fixed = document.state === "ingested";
  const untrusted = document.source_state !== "trusted";
  if (editing) {
    return (
      <tr>
        <td colSpan={6}>
          <EntryForm initial={{ url: document.url, title: document.title, version: document.version, role: document.role }}
            label="Save" busy={busy} onCancel={() => setEditing(false)}
            onSubmit={(entry) => { onEdit(document.id, entry); setEditing(false); }} />
        </td>
      </tr>
    );
  }
  return (
    <tr>
      <td>
        <input type="checkbox" aria-label="Accept" disabled={fixed || busy || (untrusted && document.state !== "accepted")}
          title={untrusted ? "Trust the source first" : undefined} checked={document.state === "accepted" || fixed}
          onChange={(event) => onDecide({ [document.id]: event.target.checked ? "accepted" : "rejected" })} />
      </td>
      <td>
        <a href={document.url} target="_blank" rel="noopener noreferrer">{document.title}</a>
        <div className="admin-panel__cell--muted" style={{ fontSize: "var(--ds-text-xs)" }}>{document.rationale}</div>
        <SourceBadge document={document} busy={busy} onTrustSource={onTrustSource} />
      </td>
      <td>{document.version ?? "—"}</td>
      <td>{document.role}</td>
      <td className="admin-panel__cell--muted">{document.outcome ?? document.state}</td>
      <td>
        {!fixed ? (
          <div className="admin-users__row-actions" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="admin-panel__action-btn" onClick={() => setEditing(true)} disabled={busy}>Edit</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
              onClick={() => onRemove(document.id)} disabled={busy}>Remove</button>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

// The catalog of one package: research proposals and the author's own entries, all editable until ingested.
export function KnowledgePackageCatalog({ pkg, busy, onTrustSource, onDecide, onAdd, onEdit, onRemove }: Props) {
  const proposed = pkg.documents.filter((document) => document.state === "proposed" && document.source_state === "trusted");
  return (
    <div>
      <div className="user-edit-panel__section-label">
        Catalog ({pkg.documents.length})
        {proposed.length ? (
          <button type="button" className="admin-panel__action-btn" style={{ marginLeft: "0.6rem" }} disabled={busy}
            onClick={() => onDecide(Object.fromEntries(proposed.map((document) => [document.id, "accepted" as const])))}>
            Accept all {proposed.length} proposals
          </button>
        ) : null}
      </div>
      <div className="admin-panel__table-wrap">
      <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
        <thead>
          <tr><th /><th>Source</th><th>Version</th><th>Role</th><th>State</th><th /></tr>
        </thead>
        <tbody>
          {pkg.documents.map((document) => (
            <DocumentRow key={document.id} document={document} busy={busy} onTrustSource={onTrustSource}
              onDecide={onDecide} onEdit={onEdit}
              onRemove={onRemove} />
          ))}
        </tbody>
      </table>
      </div>
      <div className="user-edit-panel__section-label" style={{ marginTop: "0.6rem" }}>Add a source yourself</div>
      <EntryForm key={pkg.documents.length} initial={EMPTY} label="Add" busy={busy} onSubmit={onAdd} />
    </div>
  );
}
