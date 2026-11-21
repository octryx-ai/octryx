import type { FormEvent } from "react";

import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";

// "Create workspace" in the side panel over the dimmed list (design system: forms only in the side panel). The panel
// stays open and busy ("Creating…") until the list shows the new Workspace, so nobody creates it twice.

type WorkspaceCreateDrawerProps = {
  name: string;
  description: string;
  error: string | null;
  creating: boolean;
  setName: (value: string) => void;
  setDescription: (value: string) => void;
  onSubmit: (event: FormEvent) => void | Promise<void>;
  onClose: () => void;
};

const FORM_ID = "workspace-create-form";

export function WorkspaceCreateDrawer({
  name,
  description,
  error,
  creating,
  setName,
  setDescription,
  onSubmit,
  onClose,
}: WorkspaceCreateDrawerProps) {
  return (
    <SidePanel
      title="Create workspace"
      onClose={onClose}
      testId="workspace-create-panel"
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form={FORM_ID}
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={creating || !name.trim()}
          >
            {creating ? "Creating..." : "Create workspace"}
          </button>
        </>
      }
    >
      <form id={FORM_ID} className="settings-drawer__form" onSubmit={(event) => void onSubmit(event)}>
        <FormSection title="Workspace">
          <label className="admin-panel__field">
            <span>Name (required)</span>
            <input className="admin-panel__input" value={name} onChange={(event) => setName(event.target.value)}
              required autoFocus placeholder="e.g. Claims team" />
          </label>
          <label className="admin-panel__field">
            <span>Description</span>
            <textarea className="admin-panel__input" rows={3} value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Who uses this workspace and for what" />
          </label>
        </FormSection>
        {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      </form>
    </SidePanel>
  );
}
