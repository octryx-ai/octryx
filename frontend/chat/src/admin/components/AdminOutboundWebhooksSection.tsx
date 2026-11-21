import { useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { useConfirmAction } from "./confirm/useConfirmAction";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import { AdminOutboundWebhookDrawer } from "./AdminOutboundWebhookDrawer";
import { AdminOutboundWebhookTable } from "./AdminOutboundWebhookTable";
import {
  closeOutboundWebhookDrawer, createOutboundWebhook, editOutboundWebhook, openCreateOutboundWebhook, saveOutboundWebhook,
} from "./outboundWebhookActions";
import type {
  AdminOutboundWebhookRow,
  ProjectOptionRow,
  ReadJsonFn,
} from "./webhookTypes";

type AdminOutboundWebhooksSectionProps = {
  projects: ProjectOptionRow[];
  outboundWebhooks: AdminOutboundWebhookRow[];
  showCreateOutboundWebhook: boolean;
  setShowCreateOutboundWebhook: Dispatch<SetStateAction<boolean>>;
  editingOutboundWebhookId: string | null;
  setEditingOutboundWebhookId: Dispatch<SetStateAction<string | null>>;
  outboundWebhookFormName: string;
  setOutboundWebhookFormName: Dispatch<SetStateAction<string>>;
  outboundWebhookFormUrl: string;
  setOutboundWebhookFormUrl: Dispatch<SetStateAction<string>>;
  outboundWebhookFormProjectId: string;
  setOutboundWebhookFormProjectId: Dispatch<SetStateAction<string>>;
  outboundWebhookFormEvents: string[];
  setOutboundWebhookFormEvents: Dispatch<SetStateAction<string[]>>;
  outboundWebhookFormLoading: boolean;
  setOutboundWebhookFormLoading: Dispatch<SetStateAction<boolean>>;
  outboundWebhookFormError: string | null;
  setOutboundWebhookFormError: Dispatch<SetStateAction<string | null>>;
  createdOutboundSigningSecret: string | null;
  setCreatedOutboundSigningSecret: Dispatch<SetStateAction<string | null>>;
  outboundWebhookEventOptions: readonly string[];
  readJson: ReadJsonFn;
  reloadWebhooksTab: () => void;
};

export function AdminOutboundWebhooksSection(props: AdminOutboundWebhooksSectionProps) {
  const {
    projects, outboundWebhooks, showCreateOutboundWebhook, editingOutboundWebhookId, readJson, reloadWebhooksTab,
  } = props;
  const [rowError, setRowError] = useState<string | null>(null);
  const { ask, dialog, notice } = useConfirmAction();
  const editingWebhook = editingOutboundWebhookId
    ? (outboundWebhooks.find((w) => w.id === editingOutboundWebhookId) ?? null)
    : null;

  const drawerVisible =
    showCreateOutboundWebhook || editingOutboundWebhookId !== null;

  const closeDrawer = () => closeOutboundWebhookDrawer(props);
  const openCreateWebhook = () => openCreateOutboundWebhook(props);
  const editWebhook = (hook: AdminOutboundWebhookRow) => editOutboundWebhook(props, hook);

  const toggleOutboundWebhook = async (hook: AdminOutboundWebhookRow) => {
    setRowError(null);
    try {
      await readJson(`/admin/chat/api/panel/outbound-webhooks/${hook.id}`, {
        method: "PUT",
        body: JSON.stringify({ is_active: !hook.is_active }),
      });
      reloadWebhooksTab();
    } catch (err) {
      setRowError(`${hook.name}: ${err instanceof Error ? err.message : "the change could not be saved"}.`);
    }
  };

  // Delete is confirmed in the app, naming the webhook; a refusal shows in the dialog.
  const deleteOutboundWebhook = (hook: AdminOutboundWebhookRow) => ask({
    title: `Delete outbound webhook ${hook.name}?`,
    body: <p>The platform stops calling {hook.url}. Its delivery log stays.</p>,
    confirmLabel: `Delete ${hook.name}`,
    done: `Outbound webhook ${hook.name} deleted.`,
    run: async () => {
      await readJson(`/admin/chat/api/panel/outbound-webhooks/${hook.id}`, { method: "DELETE" });
      reloadWebhooksTab();
    },
  });

  const onDrawerSave = showCreateOutboundWebhook
    ? () => createOutboundWebhook(props)
    : () => saveOutboundWebhook(props);

  return (
    <OutboundWebhooksView
      props={props} projects={projects} rowError={rowError} notice={notice} dialog={dialog}
      openCreateWebhook={openCreateWebhook} editWebhook={editWebhook} toggleOutboundWebhook={toggleOutboundWebhook}
      deleteOutboundWebhook={deleteOutboundWebhook} drawerVisible={drawerVisible} editingWebhook={editingWebhook}
      onDrawerSave={onDrawerSave} closeDrawer={closeDrawer}
    />
  );
}

type OutboundWebhooksViewProps = {
  props: AdminOutboundWebhooksSectionProps;
  projects: ProjectOptionRow[];
  rowError: string | null;
  notice: ReactNode;
  dialog: ReactNode;
  openCreateWebhook: () => void;
  editWebhook: (hook: AdminOutboundWebhookRow) => void;
  toggleOutboundWebhook: (hook: AdminOutboundWebhookRow) => Promise<void>;
  deleteOutboundWebhook: (hook: AdminOutboundWebhookRow) => void;
  drawerVisible: boolean;
  editingWebhook: AdminOutboundWebhookRow | null;
  onDrawerSave: () => Promise<void>;
  closeDrawer: () => void;
};

function OutboundWebhooksView({
  props, projects, rowError, notice, dialog, openCreateWebhook, editWebhook, toggleOutboundWebhook,
  deleteOutboundWebhook, drawerVisible, editingWebhook, onDrawerSave, closeDrawer,
}: OutboundWebhooksViewProps) {
  const { outboundWebhooks, showCreateOutboundWebhook, editingOutboundWebhookId, outboundWebhookFormName,
    setOutboundWebhookFormName, outboundWebhookFormUrl, setOutboundWebhookFormUrl, outboundWebhookFormProjectId,
    setOutboundWebhookFormProjectId, outboundWebhookEventOptions, outboundWebhookFormEvents, setOutboundWebhookFormEvents,
    outboundWebhookFormError, outboundWebhookFormLoading, createdOutboundSigningSecret } = props;
  return (
    <>
      {/* What an outbound webhook does is in the page help (help/admin/webhooks.md); no section header, the
          table is the page. */}
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={openCreateWebhook}
          data-testid="outbound-webhook-new"
        >
          New outbound webhook
        </button>
      </AdminHeaderActions>

      {notice}
      {rowError ? <p className="admin-panel__error" role="alert">{rowError}</p> : null}
      {dialog}
      <AdminOutboundWebhookTable
        outboundWebhooks={outboundWebhooks}
        projects={projects}
        onEdit={editWebhook}
        onToggleActive={toggleOutboundWebhook}
        onDelete={deleteOutboundWebhook}
        selectedKey={editingOutboundWebhookId}
      />

      <AdminOutboundWebhookDrawer
        show={drawerVisible}
        isEditing={!showCreateOutboundWebhook}
        entry={editingWebhook}
        projects={projects}
        name={outboundWebhookFormName}
        setName={setOutboundWebhookFormName}
        url={outboundWebhookFormUrl}
        setUrl={setOutboundWebhookFormUrl}
        projectId={outboundWebhookFormProjectId}
        setProjectId={setOutboundWebhookFormProjectId}
        eventOptions={outboundWebhookEventOptions}
        selectedEvents={outboundWebhookFormEvents}
        setSelectedEvents={setOutboundWebhookFormEvents}
        error={outboundWebhookFormError}
        loading={outboundWebhookFormLoading}
        signingSecret={createdOutboundSigningSecret}
        onSave={onDrawerSave}
        onClose={closeDrawer}
      />
    </>
  );
}
