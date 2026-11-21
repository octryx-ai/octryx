// Local bootstrap and setup guide requests of the admin panel.
import type { AdminProvider, LocalBootstrapStatus, SetupGuideStatus } from "../types/adminPanelTypes.usersProviders";
import type { AdminRuntime, AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";
import type { UseAdminBootstrapUserApprovalArgs } from "./adminBootstrapUserTypes";

type Args = UseAdminBootstrapUserApprovalArgs;

export function applyLocalBootstrapState(args: Args, data: LocalBootstrapStatus | null) {
  args.setLocalBootstrap(data);
  if (!data) return;
  args.setLocalBootstrapEndpointDraft(
    data.endpoint_url ||
      data.recommended_endpoint_url ||
      "http://localhost:11434",
  );
  args.setLocalBootstrapModelDraft(
    data.model_id || data.recommended_model_id || "gemma4",
  );
  args.setLocalBootstrapDisplayDraft(
    data.provider_display_name || "Local Gemma 4 Anchor",
  );
}

export async function loadSetupGuideStatus(args: Args) {
  try {
    const data = await args.readJson<SetupGuideStatus>(
      "/admin/chat/api/panel/setup-guide",
    );
    args.setSetupGuide(data);
  } catch {
    args.setSetupGuide(null);
  }
}

export async function loadLocalBootstrap(args: Args) {
  args.setLocalBootstrapLoading(true);
  try {
    const data = await args.readJson<LocalBootstrapStatus>(
      "/admin/chat/api/panel/local-bootstrap",
    );
    applyLocalBootstrapState(args, data);
    args.setLocalBootstrapError(null);
  } catch (err) {
    args.setLocalBootstrapError(
      err instanceof Error ? err.message : "Failed to load local bootstrap",
    );
  } finally {
    args.setLocalBootstrapLoading(false);
  }
}

export async function refreshBootstrap(args: Args) {
  const { readJson } = args;
  const [
    providerData,
    runtimeData,
    runtimeSettingsData,
    bootstrapData,
    setupGuideData,
  ] = await Promise.all([
    readJson<AdminProvider[]>("/admin/chat/api/panel/providers"),
    readJson<AdminRuntime[]>("/admin/chat/api/panel/runtimes"),
    readJson<AdminRuntimeSettings>("/admin/chat/api/panel/runtime-settings"),
    readJson<LocalBootstrapStatus>("/admin/chat/api/panel/local-bootstrap"),
    readJson<SetupGuideStatus>("/admin/chat/api/panel/setup-guide").catch(
      () => null,
    ),
  ]);
  args.setProviders(providerData);
  args.setRuntimes(runtimeData);
  args.setRuntimeSettings(runtimeSettingsData);
  args.setRuntimeDefaultModelDraft(runtimeSettingsData.agent_default_model || "");
  applyLocalBootstrapState(args, bootstrapData);
  args.setSetupGuide(setupGuideData);
}
