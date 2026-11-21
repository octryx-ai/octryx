import type { Dispatch, FormEvent, SetStateAction } from "react";
import { DEFAULT_PROVIDER_CREATE_DRIVER, providerCreateChoiceLabel } from "../components/providerTab/providerCreateChoices";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ReadJsonFn } from "./useAdminProviderConfigAuthActions.types";

type CreateProviderCreateActionsArgs = {
  readJson: ReadJsonFn;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  newKeyValue: string;
  setEditingKey: Dispatch<SetStateAction<string | null>>;
  setNewKeyValue: Dispatch<SetStateAction<string>>;
  setProviderFormError: Dispatch<SetStateAction<string | null>>;
  setProviderFormLoading: Dispatch<SetStateAction<boolean>>;
  newProviderDriver: string;
  newProviderDisplay: string;
  newProviderEndpointUrl: string;
  newProviderAuthMode: string;
  newProviderKey: string;
  newProviderSecretKey: string;
  newProviderSessionToken: string;
  newProviderRegion: string;
  newProviderArn: string;
  newGoogleClientId: string;
  newGoogleClientSecret: string;
  newGoogleCloudProject: string;
  setNewProviderDriver: Dispatch<SetStateAction<string>>;
  setNewProviderDisplay: Dispatch<SetStateAction<string>>;
  setNewProviderAuthMode: Dispatch<SetStateAction<string>>;
  setNewProviderKey: Dispatch<SetStateAction<string>>;
  setNewProviderSecretKey: Dispatch<SetStateAction<string>>;
  setNewProviderSessionToken: Dispatch<SetStateAction<string>>;
  setNewProviderRegion: Dispatch<SetStateAction<string>>;
  setNewProviderArn: Dispatch<SetStateAction<string>>;
  setNewProviderEndpointUrl: Dispatch<SetStateAction<string>>;
  setNewGoogleClientId: Dispatch<SetStateAction<string>>;
  setNewGoogleClientSecret: Dispatch<SetStateAction<string>>;
  setNewGoogleCloudProject: Dispatch<SetStateAction<string>>;
  setShowAddProvider: Dispatch<SetStateAction<boolean>>;
  loadSetupGuide: () => Promise<void>;
};

type Args = CreateProviderCreateActionsArgs;

// The create request body: credentials are sent only in the fields of the chosen provider and auth mode.
function newProviderBody({
  newProviderDriver,
  newProviderDisplay,
  newProviderEndpointUrl,
  newProviderAuthMode,
  newProviderKey,
  newProviderSecretKey,
  newProviderSessionToken,
  newProviderRegion,
  newProviderArn,
  newGoogleClientId,
  newGoogleClientSecret,
  newGoogleCloudProject,
}: Args) {
  return {
    driver: newProviderDriver,
    display_name: newProviderDisplay || providerCreateChoiceLabel(newProviderDriver),
    endpoint_url: newProviderEndpointUrl || undefined,
    auth_mode:
      newProviderDriver === "gemini_api"
        ? newProviderAuthMode
        : newProviderDriver === "bedrock_api" &&
            newProviderKey &&
            newProviderSecretKey
          ? "aws_credentials"
          : newProviderDriver === "ollama"
            ? "none"
            : undefined,
    api_key:
      newProviderDriver === "bedrock_api" ? undefined : newProviderKey || undefined,
    aws_access_key_id:
      newProviderDriver === "bedrock_api"
        ? newProviderKey || undefined
        : undefined,
    aws_secret_access_key:
      newProviderDriver === "bedrock_api"
        ? newProviderSecretKey || undefined
        : undefined,
    aws_session_token:
      newProviderDriver === "bedrock_api"
        ? newProviderSessionToken || undefined
        : undefined,
    aws_region: newProviderRegion || undefined,
    aws_role_arn: newProviderArn || undefined,
    google_oauth_client_id:
      newProviderDriver === "gemini_api" && newProviderAuthMode === "oauth"
        ? newGoogleClientId || undefined
        : undefined,
    google_oauth_client_secret:
      newProviderDriver === "gemini_api" && newProviderAuthMode === "oauth"
        ? newGoogleClientSecret || undefined
        : undefined,
    google_cloud_project:
      newProviderDriver === "gemini_api" && newProviderAuthMode === "oauth"
        ? newGoogleCloudProject || undefined
        : undefined,
    is_global: true,
  };
}

function resetNewProviderForm(args: Args) {
  args.setShowAddProvider(false);
  args.setNewProviderDriver(DEFAULT_PROVIDER_CREATE_DRIVER);
  args.setNewProviderDisplay("");
  args.setNewProviderAuthMode("api_key");
  args.setNewProviderKey("");
  args.setNewProviderSecretKey("");
  args.setNewProviderSessionToken("");
  args.setNewProviderRegion("");
  args.setNewProviderArn("");
  args.setNewProviderEndpointUrl("");
  args.setNewGoogleClientId("");
  args.setNewGoogleClientSecret("");
  args.setNewGoogleCloudProject("");
}

// Stores a new API key and shows it masked in the provider list.
async function saveApiKey(
  { readJson, setProviders, newKeyValue, setEditingKey, setNewKeyValue }: Args,
  providerId: string,
) {
  try {
    await readJson(`/admin/chat/api/panel/providers/${providerId}`, {
      method: "PUT",
      body: JSON.stringify({ api_key: newKeyValue }),
    });
    setProviders((prev) =>
      prev.map((provider) =>
        provider.id === providerId
          ? {
              ...provider,
              has_api_key: Boolean(newKeyValue),
              api_key_masked: newKeyValue
                ? "••••••••" + newKeyValue.slice(-4)
                : "",
            }
          : provider,
      ),
    );
    setEditingKey(null);
    setNewKeyValue("");
  } catch (err) {
    window.alert(err instanceof Error ? err.message : "Failed");
  }
}

export function createProviderCreateActions(args: Args) {
  const {
    readJson,
    setProviders,
    setProviderFormError,
    setProviderFormLoading,
    loadSetupGuide,
  } = args;
  const handleSaveApiKey = async (providerId: string) =>
    saveApiKey(args, providerId);

  const handleAddProvider = async (event: FormEvent) => {
    event.preventDefault();
    setProviderFormError(null);
    setProviderFormLoading(true);
    try {
      const created = await readJson<AdminProvider>(
        "/admin/chat/api/panel/providers",
        {
          method: "POST",
          body: JSON.stringify(newProviderBody(args)),
        },
      );
      setProviders((prev) => [...prev, created]);
      void loadSetupGuide();
      resetNewProviderForm(args);
    } catch (err) {
      setProviderFormError(err instanceof Error ? err.message : "Failed");
    } finally {
      setProviderFormLoading(false);
    }
  };

  return {
    handleAddProvider,
    handleSaveApiKey,
  };
}
