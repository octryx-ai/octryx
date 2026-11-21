import { type Dispatch, type SetStateAction, useCallback, useMemo, useState } from "react";
import { readJson } from "../utils/adminPanelHelpers";

type ExportPreviewDecision = {
  fact_id: string;
  fact_key: string;
  fact_type: string;
  action: "exportable" | "redacted" | "requires_review" | "blocked" | string;
  labels: string[];
  reasons: string[];
  redacted_paths: string[];
  redaction_types: string[];
  original_classification: string;
  export_classification?: string | null;
};

type ExportPreviewPayload = {
  node_count: number;
  missing_node_ids: string[];
  counts: Record<string, number>;
  decisions: ExportPreviewDecision[];
  preview: Array<{
    id?: string;
    key?: string;
    type?: string;
    display_name?: string;
    summary?: string;
    classification?: string;
  }>;
};

const DEFAULT_EXPORT_PREVIEW_DRAFT = {
  node_ids: "",
  reviewer_role: "",
  review_approved: false,
  customer_terms: "",
  username_terms: "",
};

function decisionBadgeClass(status: string) {
  const normalized = status.toLowerCase();
  if (["exportable"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--active";
  }
  if (["blocked"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--danger";
  }
  if (["redacted", "requires_review"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--warning";
  }
  return "admin-panel__badge";
}

function buildExportPreviewPayload(draft: typeof DEFAULT_EXPORT_PREVIEW_DRAFT) {
  return {
    node_ids: draft.node_ids
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean),
    review_approved: draft.review_approved,
    reviewer_role: draft.reviewer_role.trim() || undefined,
    export_policy: {
      customer_terms: draft.customer_terms
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      username_terms: draft.username_terms
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      allow_with_review: ["confidential", "customer_specific"],
    },
  };
}

type ExportPreviewDraft = typeof DEFAULT_EXPORT_PREVIEW_DRAFT;

type ExportPreviewFieldsProps = {
  previewDraft: ExportPreviewDraft;
  setPreviewDraft: Dispatch<SetStateAction<ExportPreviewDraft>>;
};

function ExportPreviewFields({ previewDraft, setPreviewDraft }: ExportPreviewFieldsProps) {
  return (
    <div className="admin-panel__form-grid">
      <label>
        <span className="admin-panel__form-label">Graph node IDs</span>
        <textarea
          className="admin-panel__form-input"
          value={previewDraft.node_ids}
          onChange={(event) => setPreviewDraft((current) => ({ ...current, node_ids: event.target.value }))}
          placeholder="Paste graph node IDs separated by comma or newline"
          rows={3}
        />
      </label>
      <label>
        <span className="admin-panel__form-label">Reviewer role</span>
        <select
          className="admin-panel__form-input"
          value={previewDraft.reviewer_role}
          onChange={(event) => setPreviewDraft((current) => ({ ...current, reviewer_role: event.target.value }))}
        >
          <option value="">No review approval</option>
          <option value="security">Security</option>
          <option value="data_protection">Data protection</option>
          <option value="knowledge_steward">Knowledge steward</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      <label>
        <span className="admin-panel__form-label">Customer terms</span>
        <input
          className="admin-panel__form-input"
          value={previewDraft.customer_terms}
          onChange={(event) => setPreviewDraft((current) => ({ ...current, customer_terms: event.target.value }))}
          placeholder="ACME Bank, Orion"
        />
      </label>
      <label>
        <span className="admin-panel__form-label">User handle terms</span>
        <input
          className="admin-panel__form-input"
          value={previewDraft.username_terms}
          onChange={(event) => setPreviewDraft((current) => ({ ...current, username_terms: event.target.value }))}
          placeholder="user-1, user-2"
        />
      </label>
      <label className="admin-panel__checkbox">
        <input
          type="checkbox"
          checked={previewDraft.review_approved}
          onChange={(event) =>
            setPreviewDraft((current) => ({ ...current, review_approved: event.target.checked }))
          }
        />
        <span>Reviewer approval granted</span>
      </label>
    </div>
  );
}

function ExportPreviewTable({ preview }: { preview: ExportPreviewPayload }) {
  return (
    <div className="admin-panel__table-wrap" style={{ marginTop: "0.7rem" }}>
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Fact</th>
            <th>Decision</th>
            <th>Labels</th>
            <th>Reason</th>
            <th>Redaction</th>
          </tr>
        </thead>
        <tbody>
          {preview.decisions.map((decision) => (
            <tr key={decision.fact_id || decision.fact_key}>
              <td>
                <strong>{decision.fact_key || decision.fact_id}</strong>
                <div className="admin-panel__hint">{decision.fact_type}</div>
              </td>
              <td>
                <span className={decisionBadgeClass(decision.action)}>{decision.action}</span>
                {decision.export_classification ? (
                  <div className="admin-panel__hint">export: {decision.export_classification}</div>
                ) : null}
              </td>
              <td>{decision.labels.join(", ") || "-"}</td>
              <td>{decision.reasons.join("; ")}</td>
              <td>{decision.redaction_types.join(", ") || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {preview.missing_node_ids.length ? (
        <div className="admin-panel__hint">Missing nodes: {preview.missing_node_ids.join(", ")}</div>
      ) : null}
    </div>
  );
}

export function AdminEngineeringKnowledgeExportPreviewPanel({ onError }: { onError: (message: string) => void }) {
  const [previewDraft, setPreviewDraft] = useState(DEFAULT_EXPORT_PREVIEW_DRAFT);
  const [preview, setPreview] = useState<ExportPreviewPayload | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const canPreviewExport = useMemo(() => previewDraft.node_ids.trim().length > 0, [previewDraft.node_ids]);

  const runExportPreview = useCallback(async () => {
    if (!canPreviewExport) return;
    setPreviewing(true);
    try {
      setPreview(
        await readJson<ExportPreviewPayload>("/admin/chat/api/panel/engineering-knowledge/federation/export-preview", {
          method: "POST",
          body: JSON.stringify(buildExportPreviewPayload(previewDraft)),
        }),
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  }, [canPreviewExport, onError, previewDraft]);

  return (
    <section className="admin-panel__form" style={{ marginTop: "0.9rem" }}>
      <div className="admin-panel__section-header">
        <div>
          <span className="admin-panel__section-title">Export-control preview</span>
          <div className="admin-panel__hint">Validate selected graph facts before signing a federation package.</div>
        </div>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void runExportPreview()}
          disabled={!canPreviewExport || previewing}
        >
          {previewing ? "Checking..." : "Preview export"}
        </button>
      </div>
      <ExportPreviewFields previewDraft={previewDraft} setPreviewDraft={setPreviewDraft} />
      {preview ? <ExportPreviewTable preview={preview} /> : null}
    </section>
  );
}
