import { useEffect, useState } from "react";

import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { SidePanel } from "../../../layout/SidePanel";
import { ActionMenu } from "../workflowSurfaces/ActionMenu";
import { InboundEventRows } from "./InboundEventRows";
import { InboundWebhookConnect, InboundWebhookFlow } from "./InboundWebhookDetailSections";
import { InboundWebhookSetup, InboundWebhookTestSection } from "./InboundWebhookSetupSections";
import { createDetailActions, type InboundConfirm, type InboundTestResult } from "./inboundWebhookDetailActions";
import {
  actionsForWorkspace,
  stateLine,
  type ActionOption,
  type InboundEvent,
  type InboundSource,
  type InboundWebhook,
} from "./inboundWebhookModel";

type ReadJson = <T>(input: string, init?: RequestInit) => Promise<T>;

type Props = {
  webhook: InboundWebhook;
  source: InboundSource | undefined;
  actions: ActionOption[];
  readJson: ReadJson;
  onChanged: (webhook: InboundWebhook | null) => void;
  onClose: () => void;
  // The row's ⋯ menu opens the panel with its remove confirmation already asked.
  initialConfirm?: "remove" | null;
};

// The webhook's side panel (the shared SidePanel): flow, connect (URL +
// rotate), test alert, recent alerts and setup. Pause or Resume is the footer action; Remove… sits in the ⋯ menu.
export function InboundWebhookDetailDrawer({
  webhook,
  source,
  actions,
  readJson,
  onChanged,
  onClose,
  initialConfirm = null,
}: Props) {
  const base = `/admin/chat/api/panel/webhooks/${webhook.id}`;
  const detail = useDetailState(source, initialConfirm);
  const { events, sample, setSample, testResult, error, busy, rotated, confirm, setConfirm } = detail;
  const state = stateLine(webhook);

  const { loadEvents, save, sendTest, rotate, remove } = createDetailActions({ base, webhook, readJson, onChanged, ...detail });
  useEffect(() => {
    void loadEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [webhook.id]);

  const workspaceActions = actionsForWorkspace(actions, webhook.project_id);
  return (
    <SidePanel
      title={webhook.name}
      subtitle={`Inbound webhook · ${webhook.workspace_name}`}
      onClose={onClose}
      testId="inbound-webhook-panel"
      headerActions={<RemoveMenu name={webhook.name} busy={busy} onRemove={() => setConfirm("remove")} />}
      footer={<PauseResumeButton active={webhook.is_active} busy={busy} save={save} />}
    >
      <InboundWebhookFlow webhook={webhook} state={state} />

      <InboundWebhookConnect webhook={webhook} rotated={rotated} busy={busy} save={save}
        onRotate={() => setConfirm("rotate")} />

      <InboundWebhookTestSection source={source} sample={sample} onSample={setSample} busy={busy}
        onSend={() => void sendTest()} testResult={testResult} />

      <section className="automation-drawer-section">
        <h3>Recent alerts</h3>
        <InboundEventRows events={events} />
      </section>

      <InboundWebhookSetup webhook={webhook} workspaceActions={workspaceActions} busy={busy} error={error} save={save} />

      <DetailConfirms
        confirm={confirm}
        webhookName={webhook.name}
        busy={busy}
        error={error}
        onCancel={() => setConfirm(null)}
        onRotate={() => void rotate()}
        onRemove={() => void remove()}
      />
    </SidePanel>
  );
}

function useDetailState(source: InboundSource | undefined, initialConfirm: InboundConfirm) {
  const [events, setEvents] = useState<InboundEvent[]>([]);
  const [sample, setSample] = useState(source?.samples[0]?.key ?? "");
  const [testResult, setTestResult] = useState<InboundTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rotated, setRotated] = useState<InboundWebhook | null>(null);
  const [confirm, setConfirm] = useState<InboundConfirm>(initialConfirm);
  return {
    events, setEvents, sample, setSample, testResult, setTestResult, error, setError, busy, setBusy, rotated, setRotated,
    confirm, setConfirm,
  };
}

function RemoveMenu({ name, busy, onRemove }: { name: string; busy: boolean; onRemove: () => void }) {
  return (
    <ActionMenu
      row={{ objectName: name }}
      items={[{ label: "Remove…", danger: true, disabled: busy, onSelect: onRemove, testId: "inbound-webhook-remove" }]}
    />
  );
}

function PauseResumeButton({
  active,
  busy,
  save,
}: {
  active: boolean;
  busy: boolean;
  save: (patch: Record<string, unknown>) => Promise<void>;
}) {
  return (
    <button
      type="button"
      className="admin-panel__action-btn"
      disabled={busy}
      onClick={() => void save({ is_active: !active })}
      data-testid="inbound-webhook-toggle"
    >
      {active ? "Pause" : "Resume"}
    </button>
  );
}

function DetailConfirms({
  confirm,
  webhookName,
  busy,
  error,
  onCancel,
  onRotate,
  onRemove,
}: {
  confirm: InboundConfirm;
  webhookName: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onRotate: () => void;
  onRemove: () => void;
}) {
  return (
    <>
      {confirm === "rotate" ? (
        <ConfirmDialog
          title="Rotate the signing secret?"
          confirmLabel="Rotate"
          busy={busy}
          error={error}
          onCancel={onCancel}
          onConfirm={onRotate}
        >
          <p>
            The current secret stops working at once. Update the sending tool
            with the new one.
          </p>
        </ConfirmDialog>
      ) : null}
      {confirm === "remove" ? (
        <ConfirmDialog
          title={`Remove ${webhookName}?`}
          confirmLabel="Remove webhook"
          typeToConfirm={webhookName}
          busy={busy}
          error={error}
          onCancel={onCancel}
          onConfirm={onRemove}
        >
          <p>
            Calls to its URL are refused afterwards and its alert history is
            deleted.
          </p>
        </ConfirmDialog>
      ) : null}
    </>
  );
}
