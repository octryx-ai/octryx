import { useId, useState } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { GovernedDrawer } from "../governedRegistry/GovernedDrawer";
import "../governedRegistry/governedRegistry.css";
import { FLOW_BUILDER_TEMPLATES } from "./flowBuilderTemplates";
import { BASIC_WORKFLOW_STARTER, GLOBAL_WORKFLOW_SCOPE, buildNewFlowPayload } from "./flowDraftCreation";
import type { FlowDefinitionRow } from "./flowBuilderTypes";

type Props = {
  projects: Array<{ id: string; name: string }>;
  readJson: ReadJsonFn;
  onClose: () => void;
  onCreated: (flow: FlowDefinitionRow) => void;
  // From a workspace's "Create a workflow" link: the workspace to preselect, and why none is.
  initialScope?: string;
  scopeNotice?: string | null;
};

export function FlowDraftCreateDrawer({ projects, readJson, onClose, onCreated, initialScope = "", scopeNotice = null }: Props) {
  const formId = useId();
  const [name, setName] = useState("");
  const [scope, setScope] = useState(initialScope);
  const [templateKey, setTemplateKey] = useState(BASIC_WORKFLOW_STARTER);
  const [suffix] = useState(() => crypto.randomUUID().slice(0, 8));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const template = FLOW_BUILDER_TEMPLATES.find((item) => item.key === templateKey);
  const close = () => { if (!busy) onClose(); };

  async function create() {
    if (busy) return;
    setError(null);
    if (scope !== GLOBAL_WORKFLOW_SCOPE && !projects.some((project) => project.id === scope)) {
      setError("Choose an available workspace or Global."); return;
    }
    setBusy(true);
    try {
      const payload = buildNewFlowPayload(name, scope, templateKey, suffix);
      const saved = await readJson<FlowDefinitionRow>("/api/v1/flows", { method: "POST", body: JSON.stringify(payload) });
      onCreated(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The draft could not be created.");
    } finally { setBusy(false); }
  }

  return (
    <GovernedDrawer variant="edit" eyebrow="Workflows" title="New workflow" onClose={close} footer={<>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={close}>Cancel</button>
      <button type="submit" form={formId} className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !name.trim() || !scope}>
        {busy ? "Creating…" : "Create draft"}
      </button>
    </>}>
      <form id={formId} onSubmit={(event) => { event.preventDefault(); void create(); }}>
        <p className="admin-panel__hint">Choose where this workflow belongs and how to start. Creating a draft saves it; running and publishing are separate actions.</p>
        <label className="admin-panel__field"><span>Name *</span>
          <input className="admin-panel__input" required maxLength={220} value={name} placeholder="For example, review a support request" onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="admin-panel__field"><span>Workspace *</span>
          <select className="admin-panel__input" required value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="">Choose a workspace…</option>
            <option value={GLOBAL_WORKFLOW_SCOPE}>Global (all workspaces)</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        {scopeNotice ? <p className="admin-panel__hint" role="status">{scopeNotice}</p> : null}
        <label className="admin-panel__field"><span>Starting point</span>
          <select className="admin-panel__input" value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
            <option value={BASIC_WORKFLOW_STARTER}>Simple starter — Start → Return result</option>
            {FLOW_BUILDER_TEMPLATES.map((item) => <option key={item.key} value={item.key}>{item.category} · {item.name}</option>)}
          </select>
        </label>
        <p className="admin-panel__hint">{template?.description || "Two connected steps help you learn the editor. This starter passes the request through and calls no agent or external tool."}</p>
        {template ? <p className="admin-panel__hint">Review the template's agent and tool settings before running it. Required integrations must be available in the chosen workspace.</p> : null}
        <ol className="flow-builder__creation-steps">
          <li>Create your named draft.</li><li>Select a step to edit it, or add one from the palette.</li><li>Save your changes, then use Run to test the saved revision.</li>
        </ol>
        {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      </form>
    </GovernedDrawer>
  );
}
