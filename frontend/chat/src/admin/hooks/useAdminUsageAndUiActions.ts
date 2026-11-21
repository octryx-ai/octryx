import type { Dispatch, SetStateAction } from "react";
import type { AdminTab } from "../types/adminPanelTypes.governance";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type AdminBrandingConfig = {
  app_name: string;
  logo_url: string;
  logo_svg: string;
};

type AdminTtsConfig = {
  enabled: boolean;
  default_voice: string;
  default_speed: number;
  providers: {
    id: string;
    name: string;
    voices: string[];
    has_key: boolean;
    enabled: boolean;
    priority: number;
  }[];
};

type UseAdminUsageAndUiActionsArgs = {
  readJson: ReadJsonFn;
  loadTab: (tab: AdminTab) => Promise<void>;
  brandingConfig: AdminBrandingConfig | null;
  setBrandingFormLoading: (value: boolean) => void;
  setBrandingFormError: (value: string | null) => void;
  setBrandingFormSaved: (value: boolean) => void;
  setBrandingConfig: Dispatch<SetStateAction<AdminBrandingConfig | null>>;
  ttsConfig: AdminTtsConfig | null;
  setTtsConfig: Dispatch<SetStateAction<AdminTtsConfig | null>>;
  setTtsFormError: (value: string | null) => void;
  setTtsFormLoading: (value: boolean) => void;
  setTtsFormSaved: (value: boolean) => void;
  ttsSecrets: Record<string, string>;
};

export function useAdminUsageAndUiActions({
  readJson,
  loadTab,
  brandingConfig,
  setBrandingFormLoading,
  setBrandingFormError,
  setBrandingFormSaved,
  setBrandingConfig,
  ttsConfig,
  setTtsConfig,
  setTtsFormError,
  setTtsFormLoading,
  setTtsFormSaved,
  ttsSecrets,
}: UseAdminUsageAndUiActionsArgs) {
  const handleSaveBranding = async () => {
    if (!brandingConfig) {
      return;
    }
    setBrandingFormLoading(true);
    setBrandingFormError(null);
    setBrandingFormSaved(false);
    try {
      const saved = await readJson<{
        app_name: string;
        logo_url: string;
        logo_svg: string;
      }>("/admin/chat/api/panel/branding", {
        method: "PUT",
        body: JSON.stringify(brandingConfig),
      });
      setBrandingConfig(saved);
      setBrandingFormSaved(true);
    } catch (error) {
      setBrandingFormError(
        error instanceof Error ? error.message : "Failed to save",
      );
    } finally {
      setBrandingFormLoading(false);
    }
  };

  const handleToggleTtsGlobal = async () => {
    if (!ttsConfig) {
      return;
    }
    try {
      await readJson("/admin/chat/api/v1/tts/config", {
        method: "PUT",
        body: JSON.stringify({
          enabled: !ttsConfig.enabled,
          default_voice: ttsConfig.default_voice,
          default_speed: ttsConfig.default_speed,
        }),
      });
      setTtsConfig((prev) =>
        prev
          ? {
              ...prev,
              enabled: !prev.enabled,
            }
          : prev,
      );
    } catch (error) {
      setTtsFormError(error instanceof Error ? error.message : "Failed");
    }
  };

  const handleToggleTtsProvider = async (
    providerId: string,
    provider:
      | {
          enabled: boolean;
          priority: number;
        }
      | undefined,
  ) => {
    if (!ttsConfig) {
      return;
    }
    try {
      await readJson("/admin/chat/api/v1/tts/providers", {
        method: "POST",
        body: JSON.stringify({
          provider: providerId,
          enabled: provider ? !provider.enabled : true,
          priority: provider?.priority ?? ttsConfig.providers.length + 1,
          config: {},
        }),
      });
      void loadTab("tts");
    } catch (error) {
      setTtsFormError(error instanceof Error ? error.message : "Failed");
    }
  };

  const handleSaveTtsSecrets = async () => {
    setTtsFormLoading(true);
    setTtsFormError(null);
    setTtsFormSaved(false);
    try {
      await readJson("/admin/chat/api/panel/tts/config", {
        method: "PUT",
        body: JSON.stringify(ttsSecrets),
      });
      setTtsFormSaved(true);
      window.setTimeout(() => setTtsFormSaved(false), 3000);
    } catch (error) {
      setTtsFormError(
        error instanceof Error ? error.message : "Failed to save",
      );
    } finally {
      setTtsFormLoading(false);
    }
  };

  return {
    handleSaveBranding,
    handleSaveTtsSecrets,
    handleToggleTtsGlobal,
    handleToggleTtsProvider,
  };
}
