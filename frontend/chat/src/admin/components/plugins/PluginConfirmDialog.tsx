import { useEffect, useState } from "react";

import type { ApprovalSummary } from "../../../chatDecisionTypes";
import { connectorWriteView } from "../../../chat/approval/connectorWriteView";
import "../../../chat/approval/connectorWriteCard.css";
// The dialog's buttons on the phone too (the phone app does not load the admin styles otherwise).
import "../../../styles/chat/admin-panel-actions.css";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { loadApprovalWithPreview, type Fetcher } from "./pluginUiApi";
import { toolWords, type PluginApproval } from "./pluginUiModel";

// A plugin's write waits for the person (contract §4 `confirmation_required`): the dialog belongs to Octryx, never to
// the plugin. It names the plugin and the tool in words and shows the change preview the chat shows for the same
// approval (connectorWriteView, the chat's connector-write model and styles). Approve grants this one call; the frame
// then repeats the identical call (PluginFrame). Cancel and Escape decline.
export function PluginConfirmDialog({ pluginName, approval, fetcher, busy, error, onApprove, onDecline }: {
  pluginName: string;
  approval: PluginApproval;
  fetcher: Fetcher;
  busy: boolean;
  error: string | null;
  onApprove: () => void;
  onDecline: () => void;
}) {
  const [record, setRecord] = useState<ApprovalSummary | null>(null);
  const approvalId = approval.approval_id ?? "";
  useEffect(() => {
    if (!approvalId) return;
    let live = true;
    void loadApprovalWithPreview(fetcher, approvalId).then((found) => { if (live) setRecord(found); });
    return () => { live = false; };
  }, [approvalId, fetcher]);

  const toolName = approval.tool_name || record?.changePreview?.toolName || record?.action || "";
  const preview = record?.changePreview?.preview ?? null;
  const write = connectorWriteView(preview, toolName);
  const action = write?.action ?? toolWords(toolName);
  const generic = !write && preview && typeof preview === "object" ? preview : null;
  const genericTitle = generic && typeof generic.title === "string" && !/^execute tool\b/i.test(generic.title) ? generic.title : "";
  const genericSummary = generic && typeof generic.summary === "string" ? generic.summary : "";

  return (
    <ConfirmDialog title={`${pluginName} wants to change something`} confirmLabel="Approve" tone="neutral" busy={busy}
      error={error ?? (approvalId ? null : "Octryx did not say which approval this is, so this call stays refused.")}
      confirmDisabled={!approvalId} onConfirm={onApprove} onCancel={onDecline}>
      <div className="plg-confirm" data-testid="plugin-confirm">
        <p className="plg-confirm__lead">
          The plugin <b>{pluginName}</b> asks Octryx to: <b>{write?.title ?? action}</b>
        </p>
        {write?.connector ? (
          <p className="plg-muted">Writes to {[write.connector, write.connection && write.connection !== write.connector ? `connection ${write.connection}` : ""].filter(Boolean).join(" · ")}</p>
        ) : null}
        {write && write.fields.length ? (
          <dl className="write-approval__fields" aria-label="Fields to write">
            {write.fields.map((field, index) => (
              <div key={`${field.key}-${index}`} className="write-approval__field">
                <dt>{field.label}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {genericTitle || genericSummary ? (
          <div className="plg-confirm__preview">
            {genericTitle ? <b>{genericTitle}</b> : null}
            {genericSummary ? <span>{genericSummary}</span> : null}
          </div>
        ) : null}
        <p className="plg-muted">It runs as you, with your roles. Only this call; the next change asks again.</p>
      </div>
    </ConfirmDialog>
  );
}
