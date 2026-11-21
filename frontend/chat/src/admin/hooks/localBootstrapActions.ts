// Local bootstrap actions: health check and setup of the local model runtime anchor.
import type { LocalBootstrapStatus } from "../types/adminPanelTypes.usersProviders";
import type { CreateProviderRuntimeActionsArgs } from "./useAdminProviderRuntimeActions.types";

type LocalBootstrapActionsArgs = Pick<
  CreateProviderRuntimeActionsArgs,
  | "readJson"
  | "refreshBootstrapContext"
  | "setLocalBootstrap"
  | "setLocalBootstrapActionLoading"
  | "setLocalBootstrapError"
  | "localBootstrapEndpointDraft"
  | "localBootstrapModelDraft"
  | "localBootstrapDisplayDraft"
  | "localBootstrapPullModel"
  | "localBootstrapMakePrimary"
>;

export function createLocalBootstrapActions({
  readJson,
  refreshBootstrapContext,
  setLocalBootstrap,
  setLocalBootstrapActionLoading,
  setLocalBootstrapError,
  localBootstrapEndpointDraft,
  localBootstrapModelDraft,
  localBootstrapDisplayDraft,
  localBootstrapPullModel,
  localBootstrapMakePrimary,
}: LocalBootstrapActionsArgs) {
  const handleCheckLocalBootstrap = async () => {
    setLocalBootstrapActionLoading("health");
    setLocalBootstrapError(null);
    try {
      const result = await readJson<{
        health_status: string;
        last_health_error: string;
        endpoint_url: string;
        available_models: string[];
      }>("/admin/chat/api/panel/local-bootstrap/health", {
        method: "POST",
        body: JSON.stringify({
          endpoint_url: localBootstrapEndpointDraft.trim() || undefined,
        }),
      });
      setLocalBootstrap((current) => ({
        provider_id: current?.provider_id || "",
        provider_display_name:
          current?.provider_display_name ||
          localBootstrapDisplayDraft ||
          "Local Gemma 4 Anchor",
        endpoint_url:
          result.endpoint_url ||
          localBootstrapEndpointDraft ||
          "http://localhost:11434",
        profile_name: current?.profile_name || "bootstrap",
        model_id: current?.model_id || localBootstrapModelDraft || "gemma4",
        bootstrap_role: current?.bootstrap_role || "",
        health_status: result.health_status || "",
        last_health_check_at: current?.last_health_check_at || "",
        last_health_error: result.last_health_error || "",
        runtime_target_id: current?.runtime_target_id || "",
        runtime_priority: current?.runtime_priority ?? null,
        is_primary: Boolean(current?.is_primary),
        installed: Boolean(current?.installed),
        setup_complete: Boolean(current?.setup_complete),
        available_models: result.available_models || [],
        managed_by_system: Boolean(current?.managed_by_system),
        recommended_endpoint_url:
          result.endpoint_url ||
          localBootstrapEndpointDraft ||
          "http://localhost:11434",
        recommended_model_id:
          current?.recommended_model_id || localBootstrapModelDraft || "gemma4",
      }));
    } catch (err) {
      setLocalBootstrapError(
        err instanceof Error ? err.message : "Health check failed",
      );
    } finally {
      setLocalBootstrapActionLoading(null);
    }
  };

  const handleSetupLocalBootstrap = async () => {
    setLocalBootstrapActionLoading("setup");
    setLocalBootstrapError(null);
    try {
      await readJson<LocalBootstrapStatus>(
        "/admin/chat/api/panel/local-bootstrap/setup",
        {
          method: "POST",
          body: JSON.stringify({
            endpoint_url: localBootstrapEndpointDraft.trim() || undefined,
            model_id: localBootstrapModelDraft.trim() || "gemma4",
            display_name:
              localBootstrapDisplayDraft.trim() || "Local Gemma 4 Anchor",
            pull_model: localBootstrapPullModel,
            make_primary: localBootstrapMakePrimary,
          }),
        },
      );
      await refreshBootstrapContext();
    } catch (err) {
      setLocalBootstrapError(
        err instanceof Error ? err.message : "Local bootstrap setup failed",
      );
    } finally {
      setLocalBootstrapActionLoading(null);
    }
  };

  return { handleCheckLocalBootstrap, handleSetupLocalBootstrap };
}
