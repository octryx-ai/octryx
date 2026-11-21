import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "./ConfirmDialog";

// One way to confirm a destructive action: the in-app dialog names
// the object, a field it needs is labelled and says why the button waits, the server's refusal shows in place,
// and a message confirms what happened afterwards.
export type ConfirmRequest = {
  // "Delete connector jira-shop?": the action and the object's name.
  title: string;
  body?: ReactNode;
  // "Delete jira-shop".
  confirmLabel: string;
  tone?: "danger" | "neutral";
  typeToConfirm?: string;
  // A text the action needs, e.g. the reason for revoking a device.
  field?: { label: string; placeholder: string; required?: boolean };
  run: (fieldValue: string) => Promise<unknown>;
  // "Connector jira-shop deleted."
  done: string;
};

export function useConfirmAction() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const ask = (next: ConfirmRequest) => {
    setError(null);
    setValue("");
    setNotice(null);
    setRequest(next);
  };
  const missing = Boolean(request?.field?.required) && !value.trim();

  const dialog = request ? (
    <ConfirmDialog title={request.title} confirmLabel={request.confirmLabel} tone={request.tone}
      typeToConfirm={request.typeToConfirm} busy={busy} error={error} confirmDisabled={missing}
      onCancel={() => { if (!busy) setRequest(null); }}
      onConfirm={() => {
        setBusy(true);
        setError(null);
        void request.run(value.trim())
          .then(() => { setNotice(request.done); setRequest(null); })
          .catch((failure: unknown) => setError(failure instanceof Error && failure.message ? failure.message : "The action failed."))
          .finally(() => setBusy(false));
      }}>
      {request.body}
      {request.field ? (
        <label className="admin-panel__field">
          <span>{request.field.label}{request.field.required ? " (required)" : ""}</span>
          <textarea className="admin-panel__input" rows={2} value={value} placeholder={request.field.placeholder}
            onChange={(event) => setValue(event.target.value)} />
          {missing ? <span className="confirm-dialog__why">Enter {request.field.label.toLowerCase()} to continue.</span> : null}
        </label>
      ) : null}
    </ConfirmDialog>
  ) : null;

  const noticeNode = notice ? (
    <div className="admin-panel__success confirm-action__notice" role="status" data-testid="action-done">
      <span>{notice}</span>
      <button type="button" className="admin-panel__action-btn" onClick={() => setNotice(null)}>Dismiss</button>
    </div>
  ) : null;

  return { ask, dialog, notice: noticeNode };
}
