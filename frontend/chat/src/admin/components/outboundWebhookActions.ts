// The outbound webhooks section's form actions: reset, open, create, save and edit, each reading the section's
// form state and setters at call time.
import type { Dispatch, SetStateAction } from "react";
import type { AdminOutboundWebhookRow, ProjectOptionRow, ReadJsonFn } from "./webhookTypes";

export type OutboundWebhookForm = {
  projects: ProjectOptionRow[];
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
  setOutboundWebhookFormLoading: Dispatch<SetStateAction<boolean>>;
  setOutboundWebhookFormError: Dispatch<SetStateAction<string | null>>;
  setCreatedOutboundSigningSecret: Dispatch<SetStateAction<string | null>>;
  readJson: ReadJsonFn;
  reloadWebhooksTab: () => void;
};

export function resetOutboundWebhookForm(form: OutboundWebhookForm) {
  form.setOutboundWebhookFormName("");
  form.setOutboundWebhookFormUrl("");
  form.setOutboundWebhookFormProjectId(form.projects[0]?.id ?? "");
  form.setOutboundWebhookFormEvents(["task.completed"]);
}

export function closeOutboundWebhookDrawer(form: OutboundWebhookForm) {
  form.setShowCreateOutboundWebhook(false);
  form.setEditingOutboundWebhookId(null);
  form.setOutboundWebhookFormError(null);
  form.setCreatedOutboundSigningSecret(null);
  resetOutboundWebhookForm(form);
}

export function openCreateOutboundWebhook(form: OutboundWebhookForm) {
  form.setEditingOutboundWebhookId(null);
  resetOutboundWebhookForm(form);
  form.setOutboundWebhookFormError(null);
  form.setCreatedOutboundSigningSecret(null);
  form.setShowCreateOutboundWebhook(true);
}

function formBody(form: OutboundWebhookForm) {
  return {
    name: form.outboundWebhookFormName.trim(),
    url: form.outboundWebhookFormUrl.trim(),
    project_id: form.outboundWebhookFormProjectId.trim() || null,
    event_types: form.outboundWebhookFormEvents,
  };
}

const missingNameOrUrl = (form: OutboundWebhookForm) =>
  !form.outboundWebhookFormName.trim() || !form.outboundWebhookFormUrl.trim();

export async function createOutboundWebhook(form: OutboundWebhookForm) {
  if (missingNameOrUrl(form)) {
    form.setOutboundWebhookFormError("Name and target URL are required");
    return;
  }
  if (form.outboundWebhookFormEvents.length === 0) {
    form.setOutboundWebhookFormError("Select at least one event type");
    return;
  }
  form.setOutboundWebhookFormLoading(true);
  form.setOutboundWebhookFormError(null);
  try {
    const created = await form.readJson<{ signing_secret?: string }>(
      "/admin/chat/api/panel/outbound-webhooks",
      { method: "POST", body: JSON.stringify({ ...formBody(form), is_active: true }) },
    );
    form.setCreatedOutboundSigningSecret(created.signing_secret ?? null);
    form.reloadWebhooksTab();
  } catch (err) {
    form.setOutboundWebhookFormError(err instanceof Error ? err.message : "Failed to create outbound webhook");
  } finally {
    form.setOutboundWebhookFormLoading(false);
  }
}

export async function saveOutboundWebhook(form: OutboundWebhookForm) {
  if (!form.editingOutboundWebhookId) return;
  if (missingNameOrUrl(form)) {
    form.setOutboundWebhookFormError("Name and target URL are required");
    return;
  }
  form.setOutboundWebhookFormLoading(true);
  form.setOutboundWebhookFormError(null);
  try {
    await form.readJson(
      `/admin/chat/api/panel/outbound-webhooks/${form.editingOutboundWebhookId}`,
      { method: "PUT", body: JSON.stringify(formBody(form)) },
    );
    closeOutboundWebhookDrawer(form);
    form.reloadWebhooksTab();
  } catch (err) {
    form.setOutboundWebhookFormError(err instanceof Error ? err.message : "Failed to update outbound webhook");
  } finally {
    form.setOutboundWebhookFormLoading(false);
  }
}

export function editOutboundWebhook(form: OutboundWebhookForm, hook: AdminOutboundWebhookRow) {
  form.setShowCreateOutboundWebhook(false);
  form.setEditingOutboundWebhookId(hook.id);
  form.setOutboundWebhookFormError(null);
  form.setCreatedOutboundSigningSecret(null);
  form.setOutboundWebhookFormName(hook.name ?? "");
  form.setOutboundWebhookFormUrl(hook.url ?? "");
  form.setOutboundWebhookFormProjectId(hook.project_id ?? "");
  form.setOutboundWebhookFormEvents(hook.event_types ?? ["task.completed"]);
}
