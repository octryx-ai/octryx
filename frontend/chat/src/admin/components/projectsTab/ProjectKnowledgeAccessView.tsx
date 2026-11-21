// Knowledge access view of the project resources: owned base, central workspace access and knowledge mounts.
import type { Dispatch, SetStateAction } from "react";
import type { KnowledgeBaseOption, ProjectResourcePayload } from "./projectResourcesTypes";

type KnowledgeAccessViewProps = {
  payload: ProjectResourcePayload;
  saving: boolean;
  knowledgeAccess: { mode: string; default_workspace_access: boolean };
  toggleWorkspaceKnowledgeAccess: () => void;
  removeKnowledgeMount: (sourceProjectId: string) => void;
  selectedMountProjectId: string;
  setSelectedMountProjectId: Dispatch<SetStateAction<string>>;
  mountLabel: string;
  setMountLabel: Dispatch<SetStateAction<string>>;
  availableKnowledgeBases: KnowledgeBaseOption[];
  addKnowledgeMount: () => void;
};

// The knowledge base this project owns.
function OwnedKnowledgeBaseCard({ payload }: Pick<KnowledgeAccessViewProps, "payload">) {
  return (
    <div className="connector-card connector-card--configured">
      <div className="connector-card__header">
        <div className="connector-card__info">
          <div className="connector-card__name-row">
            <div className="connector-card__name">
              {payload.knowledge_base.project_name}
            </div>
            <span className="connector-card__meta-badge">owned</span>
          </div>
          <div className="connector-card__meta">
            This project owns this knowledge base. Mounts below give it
            read access to other project knowledge bases (entity graph).
          </div>
        </div>
      </div>
    </div>
  );
}

// Whether the project reads the central workspace Knowledge.
function WorkspaceKnowledgeAccessCard({ saving, knowledgeAccess, toggleWorkspaceKnowledgeAccess }: Pick<
  KnowledgeAccessViewProps, "saving" | "knowledgeAccess" | "toggleWorkspaceKnowledgeAccess"
>) {
  return (
    <div className="connector-card connector-card--configured">
      <div className="connector-card__header">
        <div className="connector-card__info">
          <div className="connector-card__name-row">
            <div className="connector-card__name">
              Workspace Knowledge access
            </div>
            <span className="connector-card__meta-badge">
              {knowledgeAccess.default_workspace_access
                ? "default"
                : "limited"}
            </span>
          </div>
          <div className="connector-card__meta">
            Central workspace Knowledge is readable unless this project is
            limited.
          </div>
        </div>
        <div className="connector-card__header-right">
          <label className="admin-checkbox-row">
            <input
              type="checkbox"
              checked={knowledgeAccess.default_workspace_access}
              disabled={saving}
              onChange={toggleWorkspaceKnowledgeAccess}
            />
            <span>Read central workspace Knowledge</span>
          </label>
        </div>
      </div>
    </div>
  );
}

// The mounted knowledge bases, each with Remove.
function KnowledgeMountList({ payload, saving, removeKnowledgeMount }: Pick<
  KnowledgeAccessViewProps, "payload" | "saving" | "removeKnowledgeMount"
>) {
  return (
  <div className="connector-grid">
    {payload.knowledge_mounts.length === 0 ? (
      <div className="admin-panel__empty-state">
        No knowledge mounts are configured.
      </div>
    ) : null}
    {payload.knowledge_mounts.map((mount) => (
      <div
        key={mount.source_project_id}
        className="connector-card connector-card--configured"
      >
        <div className="connector-card__header">
          <div className="connector-card__info">
            <div className="connector-card__name-row">
              <div className="connector-card__name">
                {mount.mount_label || mount.source_project_name}
              </div>
              <span className="connector-card__meta-badge">
                read-only
              </span>
            </div>
            <div className="connector-card__meta">
              Source: {mount.source_project_name}
            </div>
          </div>
          <div className="connector-card__header-right">
            <button
              type="button"
              className="admin-panel__danger-btn"
              disabled={saving}
              onClick={() =>
                removeKnowledgeMount(mount.source_project_id)
              }
            >
              Remove
            </button>
          </div>
        </div>
      </div>
    ))}
  </div>
  );
}

// Choose another project knowledge base and a label, and mount it.
function KnowledgeMountForm({
  saving,
  selectedMountProjectId,
  setSelectedMountProjectId,
  mountLabel,
  setMountLabel,
  availableKnowledgeBases,
  addKnowledgeMount,
}: Omit<KnowledgeAccessViewProps, "payload" | "knowledgeAccess" | "toggleWorkspaceKnowledgeAccess" | "removeKnowledgeMount">) {
  return (
  <div className="connector-fields-grid">
    <label className="connector-field">
      <span className="connector-field__label">Mount source</span>
      <select
        className="connector-field__input"
        value={selectedMountProjectId}
        onChange={(event) =>
          setSelectedMountProjectId(event.target.value)
        }
      >
        <option value="">Select project knowledge base</option>
        {availableKnowledgeBases.map((option) => (
          <option key={option.project_id} value={option.project_id}>
            {option.project_name}
          </option>
        ))}
      </select>
    </label>
    <label className="connector-field">
      <span className="connector-field__label">Mount label</span>
      <input
        className="connector-field__input"
        value={mountLabel}
        onChange={(event) => setMountLabel(event.target.value)}
      />
    </label>
    <button
      type="button"
      className="admin-panel__action-btn"
      disabled={
        saving ||
        !selectedMountProjectId ||
        availableKnowledgeBases.length === 0
      }
      onClick={addKnowledgeMount}
    >
      Add mount
    </button>
    {availableKnowledgeBases.length === 0 ? (
      <div className="admin-panel__hint">
        No additional active project knowledge bases are available to
        mount.
      </div>
    ) : null}
  </div>
  );
}

export function ProjectKnowledgeAccessView(props: KnowledgeAccessViewProps) {
  return (
    <div className="admin-modal__stack">
      <div className="admin-panel__section-header">
        <span>Knowledge base access</span>
      </div>
      <OwnedKnowledgeBaseCard payload={props.payload} />
      <WorkspaceKnowledgeAccessCard {...props} />
      <details className="admin-modal__stack">
        <summary className="admin-panel__section-header">
          <span>Knowledge mounts</span>
        </summary>
        <p className="admin-panel__hint">
          Mounts give this project read access to another project knowledge
          base. Governed Knowledge uses Workspace bindings instead.
        </p>
        <KnowledgeMountList {...props} />
        <KnowledgeMountForm {...props} />
      </details>
    </div>
  );
}
