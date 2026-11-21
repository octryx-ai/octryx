import { useState } from "react";

// Voice and branding state of the admin shell. Observability → Usage & costs loads its own data.

type TtsConfigPayload = {
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

type BrandingConfigPayload = {
  app_name: string;
  logo_url: string;
  logo_svg: string;
};

export function useAdminUsageBrandingState() {
  const [ttsConfig, setTtsConfig] = useState<TtsConfigPayload | null>(null);
  const [ttsSecrets, setTtsSecrets] = useState<Record<string, string>>({});
  const [ttsFormLoading, setTtsFormLoading] = useState(false);
  const [ttsFormError, setTtsFormError] = useState<string | null>(null);
  const [ttsFormSaved, setTtsFormSaved] = useState(false);

  const [brandingConfig, setBrandingConfig] =
    useState<BrandingConfigPayload | null>(null);
  const [brandingFormLoading, setBrandingFormLoading] = useState(false);
  const [brandingFormError, setBrandingFormError] = useState<string | null>(
    null,
  );
  const [brandingFormSaved, setBrandingFormSaved] = useState(false);

  return {
    brandingConfig,
    setBrandingConfig,
    brandingFormError,
    setBrandingFormError,
    brandingFormLoading,
    setBrandingFormLoading,
    brandingFormSaved,
    setBrandingFormSaved,
    ttsConfig,
    setTtsConfig,
    ttsFormError,
    setTtsFormError,
    ttsFormLoading,
    setTtsFormLoading,
    ttsFormSaved,
    setTtsFormSaved,
    ttsSecrets,
    setTtsSecrets,
  };
}
