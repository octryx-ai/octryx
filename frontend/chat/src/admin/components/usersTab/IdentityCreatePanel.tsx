import type { FormEvent, ReactNode } from "react";

import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";

// The create panel of the identity pages: a side panel over the dimmed list with a
// labelled form; Cancel and the primary action at the bottom right. The form submits (`form=`).
type IdentityCreatePanelProps = {
  title: string;
  section: string;
  formId: string;
  submitLabel: string;
  busyLabel: string;
  busy: boolean;
  error?: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
  testId: string;
  children: ReactNode;
};

export function IdentityCreatePanel({
  title, section, formId, submitLabel, busyLabel, busy, error, onSubmit, onClose, testId, children,
}: IdentityCreatePanelProps) {
  return (
    <SidePanel
      title={title}
      onClose={onClose}
      testId={testId}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="submit" form={formId} className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
            data-testid={`${testId}-submit`}>
            {busy ? busyLabel : submitLabel}
          </button>
        </>
      )}
    >
      <form id={formId} onSubmit={onSubmit} aria-label={title}>
        <FormSection title={section}>{children}</FormSection>
        {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      </form>
    </SidePanel>
  );
}
