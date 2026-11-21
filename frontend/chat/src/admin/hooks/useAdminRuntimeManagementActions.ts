import {
  applyRuntimeSettingsToDrafts,
  buildRuntimeSettingsPayload,
  type RuntimeSettingsSection,
} from "./useAdminRuntimeManagementActions.helpers";
import type { AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";
import type { RuntimeSettingsActionArgs } from "./useAdminRuntimeManagementActions.types";

export function createHandleSaveRuntimeSettings(
  args: RuntimeSettingsActionArgs,
) {
  const { readJson } = args;

  return async (section: RuntimeSettingsSection) => {
    try {
      const updated = await readJson<AdminRuntimeSettings>(
        "/admin/chat/api/panel/runtime-settings",
        {
          method: "PUT",
          body: JSON.stringify(buildRuntimeSettingsPayload(args, section)),
        },
      );
      applyRuntimeSettingsToDrafts(updated, args);
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "Failed to save runtime settings",
      );
    }
  };
}
