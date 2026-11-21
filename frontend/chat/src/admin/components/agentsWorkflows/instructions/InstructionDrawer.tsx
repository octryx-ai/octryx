// One instruction (mock "Instruction" drawer): key, scope, binding (always · when a workflow is selected · on request),
// the text with its token count against the layer budget, the conflict check, and the governed lifecycle: save a
// draft, submit it for four-eyes review (findings must be accepted explicitly), publish once approved.
import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { SettingsDrawer } from "../../projectsTab/SettingsDrawer";
import { Badge } from "../awBadges";
import type { SetupOptions } from "../effectiveSetup/effectiveSetupModel";
import { findingText, type InstructionBinding, type InstructionRow, type InstructionScope } from "./instructionsModel";
import { useInstructionDrawer, type InstructionDrawerState } from "./useInstructionDrawer";

const BINDINGS: { value: InstructionBinding; title: string; description: string }[] = [
  { value: "always", title: "Always", description: "Every session in the scope" },
  { value: "workflow", title: "When a workflow is selected", description: "Only turns of that workflow" },
  { value: "on_request", title: "On request only", description: "The model fetches it by exact key" },
];
const LAYER_BUDGET: Record<string, number> = { agent: 800, workspace: 1500, workflow: 1500, on_request: 3000 };

type Props = {
  row: InstructionRow | null;
  options: SetupOptions;
  readJson: ReadJsonFn;
  onClose: () => void;
  onChanged: () => void;
};

type PartProps = { state: InstructionDrawerState; options: SetupOptions };

export function InstructionDrawer({ row, options, readJson, onClose, onChanged }: Props) {
  const state = useInstructionDrawer(row, readJson, onChanged);
  const { current, draft, problem, tokens, set } = state;
  const layer = draft.binding === "on_request" ? "on_request" : draft.binding === "workflow" ? "workflow"
    : draft.scopeType === "agent" ? "agent" : "workspace";

  return (
    <SettingsDrawer
      eyebrow={current ? `Instruction · ${current.scopeType}` : "New instruction"}
      title={current?.title || "New instruction"}
      size="detail"
      onClose={onClose}
      footer={<InstructionFooter state={state} onClose={onClose} />}
    >
      {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
      <InstructionFields state={state} options={options} />
      <InstructionBindingSection state={state} options={options} />
      <label className="admin-panel__field">
        <span>{`Text · ${tokens} tokens (layer budget ${LAYER_BUDGET[layer]})`}</span>
        <textarea className="aw-textarea" rows={10} value={draft.body} onChange={(event) => set({ body: event.target.value })} />
      </label>
      <InstructionConflicts state={state} />
      <section className="work-detail__section">
        <h3>Preview</h3>
        <div className="aw-sub aw-sub--flush">See it in place on Effective setup: agent → Workspace → workflow, with its key and version.</div>
      </section>
    </SettingsDrawer>
  );
}

function InstructionFooter({ state, onClose }: { state: InstructionDrawerState; onClose: () => void }) {
  const { current, draft, findings, accept, busy, latest, saveDraft, submit, publish } = state;
  const blocking = Boolean(findings && findings.length && !accept);
  const canSave = Boolean(draft.body.trim()) && (current || (draft.key.trim() && draft.title.trim()
    && (draft.scopeType === "global" || draft.scopeId) && (draft.binding !== "workflow" || draft.workflowKey)));
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      <button type="button" className="admin-panel__action-btn" disabled={busy || !canSave} onClick={() => void saveDraft()}>
        Save draft
      </button>
      {latest?.state === "in_review" ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
          onClick={() => void publish()}>
          Publish
        </button>
      ) : (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy || latest?.state !== "draft" || blocking} onClick={() => void submit()}>
          Submit for review
        </button>
      )}
    </>
  );
}

function InstructionFields({ state: { current, draft, set }, options }: PartProps) {
  const scopeTargets = draft.scopeType === "workspace" ? options.projects : draft.scopeType === "agent" ? options.agents : [];
  return (
    <div className="admin-panel__form-grid">
      <label className="admin-panel__field">
        <span>Key</span>
        <input className="aw-mono" value={draft.key} disabled={Boolean(current)} onChange={(event) => set({ key: event.target.value })} />
      </label>
      <label className="admin-panel__field">
        <span>Title</span>
        <input value={draft.title} disabled={Boolean(current)} onChange={(event) => set({ title: event.target.value })} />
      </label>
      <label className="admin-panel__field">
        <span>Scope</span>
        <select value={draft.scopeType} disabled={Boolean(current)}
          onChange={(event) => set({ scopeType: event.target.value as InstructionScope, scopeId: "" })}>
          <option value="global">Global</option>
          <option value="workspace">Workspace</option>
          <option value="agent">Agent</option>
        </select>
      </label>
      {draft.scopeType !== "global" ? (
        <label className="admin-panel__field">
          <span>{draft.scopeType === "workspace" ? "Workspace" : "Agent"}</span>
          <select value={draft.scopeId} disabled={Boolean(current)} onChange={(event) => set({ scopeId: event.target.value })}>
            <option value="">Choose…</option>
            {scopeTargets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
      ) : null}
    </div>
  );
}

function InstructionBindingSection({ state: { current, draft, set }, options }: PartProps) {
  return (
    <section className="work-detail__section">
      <h3>Binding</h3>
      <div className="aw-choice-grid">
        {BINDINGS.map((option) => (
          <label key={option.value} className="admin-option-card">
            <input type="radio" name="instruction-binding" checked={draft.binding === option.value}
              disabled={Boolean(current)} onChange={() => set({ binding: option.value })} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{option.title}</span>
              <span className="admin-option-card__desc">{option.description}</span>
            </span>
          </label>
        ))}
      </div>
      {draft.binding === "workflow" ? (
        <label className="admin-panel__field">
          <span>Workflow</span>
          <select value={draft.workflowKey} disabled={Boolean(current)} onChange={(event) => set({ workflowKey: event.target.value })}>
            <option value="">Choose…</option>
            {options.workflows.map((item) => <option key={item.key} value={item.key}>{item.title || item.key}</option>)}
          </select>
        </label>
      ) : null}
    </section>
  );
}

function InstructionConflicts({ state: { findings, latest, accept, setAccept, selfApprove } }: { state: InstructionDrawerState }) {
  return (
    <section className="work-detail__section">
      <h3>Conflict check</h3>
      {findings === null ? <div className="aw-sub aw-sub--flush">Runs when a draft is saved.</div> : null}
      {findings && findings.length === 0 ? (
        <div className="aw-findings"><div className="aw-finding"><Badge kind="active">clear</Badge><span>No conflict found.</span></div></div>
      ) : null}
      {findings && findings.length ? (
        <>
          <div className="aw-findings">
            {findings.map((finding, index) => (
              <div className="aw-finding" key={`${finding.code}-${index}`}>
                <Badge kind="danger">{finding.code.replace(/_/g, " ")}</Badge>
                <span>
                  {findingText(finding)}
                  {finding.code === "tool_forbidden_by_policy" && finding.detail ? (
                    <span className="aw-sub aw-mono" data-finding-policy="">{finding.detail}</span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
          {latest?.state === "draft" ? (
            <label className="admin-panel__checkbox">
              <input type="checkbox" checked={accept} onChange={(event) => setAccept(event.target.checked)} />
              Accept these findings for review (audited)
            </label>
          ) : null}
        </>
      ) : null}
      {latest?.state === "in_review" && !selfApprove ? (
        <div className="aw-sub aw-sub--flush">In review: a second admin approves it from their Inbox (the bell), then publish.</div>
      ) : null}
    </section>
  );
}
