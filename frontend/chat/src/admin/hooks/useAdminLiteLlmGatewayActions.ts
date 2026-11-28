import { boundedAdminErrorText } from "../components/providerTab/litellmGatewayContract";
import type { Dispatch, SetStateAction } from "react";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { GatewayCreatePayload, GatewayUpdatePayload } from "../components/providerTab/litellmGatewayTypes";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

// Create/update actions for the governed LiteLLM gateway provider.
//
// They own only the two canonical provider calls, and they never carry a
// credential field: the gateway virtual key lives behind
// LLMProvider.api_key_secret_ref and no canonical Admin API accepts an existing
// secret reference, so it cannot be set from here at all.

const PROVIDERS_PATH = "/admin/chat/api/panel/providers";

const CREATE_FAILED_MESSAGE =
  "Creating the LiteLLM gateway provider failed. Check the governed fields and retry.";
const UPDATE_FAILED_MESSAGE =
  "Saving the LiteLLM gateway configuration failed. Check the governed fields and retry.";

export type LiteLlmGatewayActionResult = {
  ok: boolean;
  error: string | null;
};

type LiteLlmGatewayActionsArgs = {
  readJson: ReadJsonFn;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
};

export function createLiteLlmGatewayActions({
  readJson,
  setProviders,
  setShowAddProvider,
}: LiteLlmGatewayActionsArgs) {
  const handleCreateLiteLlmGatewayProvider = async (
    payload: GatewayCreatePayload,
  ): Promise<LiteLlmGatewayActionResult> => {
    try {
      const created = await readJson<AdminProvider>(PROVIDERS_PATH, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setProviders((prev) => [...prev, created]);
      setShowAddProvider(false);
      return { ok: true, error: null };
    } catch (err) {
      return {
        ok: false,
        error: boundedAdminErrorText(err, CREATE_FAILED_MESSAGE),
      };
    }
  };

  const handleUpdateLiteLlmGatewayProvider = async (
    providerId: string,
    payload: GatewayUpdatePayload,
  ): Promise<LiteLlmGatewayActionResult> => {
    try {
      const updated = await readJson<AdminProvider>(
        `${PROVIDERS_PATH}/${providerId}`,
        { method: "PUT", body: JSON.stringify(payload) },
      );
      setProviders((prev) =>
        prev.map((provider) =>
          provider.id === providerId ? updated : provider,
        ),
      );
      return { ok: true, error: null };
    } catch (err) {
      return {
        ok: false,
        error: boundedAdminErrorText(err, UPDATE_FAILED_MESSAGE),
      };
    }
  };

  return {
    handleCreateLiteLlmGatewayProvider,
    handleUpdateLiteLlmGatewayProvider,
  };
}
