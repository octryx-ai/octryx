import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { readStt, readTts, sttSaveBody, ttsSaveBodies } from "./voiceContract";
import type { SttState, TtsState } from "./voiceContract";

const TTS_CONFIG = "/chat/api/v1/tts/config";
const TTS_PROVIDER = "/chat/api/v1/tts/providers";
const TTS_KEYS = "/admin/chat/api/panel/tts/config";
const STT_CONFIG = "/admin/chat/api/panel/stt/config";
const SYNTHESIZE = "/chat/api/v1/tts/synthesize";

export type Message = { error: boolean; text: string } | null;

// The TTS and STT settings with the typed keys, loaded once; save writes all of them and reloads.
export function useVoiceSettings() {
  const [tts, setTts] = useState<TtsState | null>(null);
  const [typedKeys, setTypedKeys] = useState<Record<string, string>>({});
  const [stt, setStt] = useState<SttState | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [saving, setSaving] = useState(false);

  const load = () => {
    Promise.all([readJson<unknown>(TTS_CONFIG), readJson<unknown>(TTS_KEYS), readJson<unknown>(STT_CONFIG)])
      .then(([config, keys, sttConfig]) => {
        setTts(readTts(config, keys));
        setStt(readStt(sttConfig));
        setTypedKeys({});
      })
      .catch(() => setMessage({ error: true, text: "Voice settings could not be loaded (platform admin role required)." }));
  };
  useEffect(load, []);

  return { tts, setTts, typedKeys, setTypedKeys, stt, setStt, message, setMessage, saving, setSaving, load };
}

type VoiceSettings = ReturnType<typeof useVoiceSettings>;

// Keys first (only typed ones), then the TTS provider and config, then speech to text; reloads after success.
export async function saveVoiceSettings({ tts, stt, typedKeys, setSaving, setMessage, load }: VoiceSettings) {
  if (!tts || !stt) return;
  setSaving(true);
  setMessage(null);
  const bodies = ttsSaveBodies(tts, typedKeys);
  try {
    if (Object.keys(bodies.keys).length) {
      await readJson(TTS_KEYS, { method: "PUT", body: JSON.stringify(bodies.keys) });
    }
    await readJson(TTS_PROVIDER, { method: "POST", body: JSON.stringify(bodies.provider) });
    await readJson(TTS_CONFIG, { method: "PUT", body: JSON.stringify(bodies.config) });
    await readJson(STT_CONFIG, { method: "PUT", body: JSON.stringify(sttSaveBody(stt)) });
    setMessage({ error: false, text: "Saved: voice & speech only." });
    load();
  } catch (failure) {
    setMessage({ error: true, text: `Not saved: ${failure instanceof Error ? failure.message : "the change was refused"}.` });
  } finally {
    setSaving(false);
  }
}

// Plays a test sentence with the saved provider.
export async function playVoiceTest(setMessage: VoiceSettings["setMessage"]) {
  setMessage(null);
  try {
    const response = await fetch(SYNTHESIZE, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Hello from the platform." }),
    });
    if (!response.ok) throw new Error(String(response.status));
    await new Audio(URL.createObjectURL(await response.blob())).play();
  } catch {
    setMessage({ error: true, text: "The test sentence could not be played. Save a ready provider first." });
  }
}
