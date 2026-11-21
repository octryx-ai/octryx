// Voice settings state of one Workspace: global TTS providers, the stored project config and the save request.
import { useEffect, useState } from "react";

import type { GlobalTtsConfig, ProjectConfig } from "./projectVoiceTypes";

type ReadJson = (url: string, init?: RequestInit) => Promise<unknown>;

type VoiceSetters = {
  setProjectConfig: (config: ProjectConfig) => void;
  setTtsEnabled: (value: boolean) => void;
  setTtsProvider: (value: string) => void;
  setTtsVoice: (value: string) => void;
  setTtsSpeed: (value: number) => void;
  setSttEnabled: (value: boolean) => void;
};

type VoiceValues = { ttsEnabled: boolean; ttsProvider: string; ttsVoice: string; ttsSpeed: number; sttEnabled: boolean };

async function loadGlobalTts(readJson: unknown, setGlobalTts: (data: GlobalTtsConfig) => void) {
  try {
    const data = await (
      readJson as (url: string) => Promise<GlobalTtsConfig>
    )("/admin/chat/api/v1/tts/providers");
    setGlobalTts(data);
  } catch {
    // Global TTS may not be configured — providers list will be empty
  }
}

async function loadProjectVoice(readJson: unknown, projectId: string, set: VoiceSetters) {
  try {
    const data = await (
      readJson as (
        url: string,
      ) => Promise<{ id: string; name: string; config: ProjectConfig }>
    )(`/admin/chat/api/panel/projects/${projectId}/config`);
    const config = (data.config as ProjectConfig) || {};
    set.setProjectConfig(config);
    const tts = config?.tts;
    const stt = config?.stt;
    if (tts) {
      set.setTtsEnabled(tts.enabled ?? false);
      set.setTtsProvider(tts.provider ?? "openai");
      set.setTtsVoice(tts.default_voice ?? "alloy");
      set.setTtsSpeed(tts.default_speed ?? 1.0);
    }
    if (stt) {
      set.setSttEnabled(stt.enabled ?? false);
    }
  } catch {
    // Project may not have config yet
  }
}

function saveProjectVoice(readJson: unknown, projectId: string, values: VoiceValues) {
  return (readJson as ReadJson)(
    `/admin/chat/api/panel/projects/${projectId}/config`,
    {
      method: "PUT",
      body: JSON.stringify({
        tts: {
          enabled: values.ttsEnabled,
          provider: values.ttsProvider,
          default_voice: values.ttsVoice,
          default_speed: values.ttsSpeed,
        },
        stt: {
          enabled: values.sttEnabled,
        },
      }),
    },
  );
}

export function useProjectVoiceSettings(projectId: string | undefined, readJson: unknown) {
  const [globalTts, setGlobalTts] = useState<GlobalTtsConfig | null>(null);
  const [, setProjectConfig] = useState<ProjectConfig>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Local form state
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [ttsProvider, setTtsProvider] = useState("openai");
  const [ttsVoice, setTtsVoice] = useState("alloy");
  const [ttsSpeed, setTtsSpeed] = useState(1.0);
  const [sttEnabled, setSttEnabled] = useState(false);

  // Load global TTS providers for dropdown options
  useEffect(() => {
    if (!readJson) return;
    void loadGlobalTts(readJson, setGlobalTts);
  }, [readJson]);

  // Load project's existing config
  useEffect(() => {
    if (!projectId || !readJson) return;
    void loadProjectVoice(readJson, projectId, {
      setProjectConfig, setTtsEnabled, setTtsProvider, setTtsVoice, setTtsSpeed, setSttEnabled,
    });
  }, [projectId, readJson]);

  const handleSave = async () => {
    if (!projectId || !readJson) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await saveProjectVoice(readJson, projectId, { ttsEnabled, ttsProvider, ttsVoice, ttsSpeed, sttEnabled });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return {
    globalTts, saving, saved, error, handleSave, ttsEnabled, setTtsEnabled, ttsProvider, setTtsProvider, ttsVoice,
    setTtsVoice, ttsSpeed, setTtsSpeed, sttEnabled, setSttEnabled,
  };
}
