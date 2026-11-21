// Runtime → Capabilities → Voice & speech. Pure: no requests, no React.
//
// Only providers the backend builds are offered (services/tts/service.py `_build_tts_provider`; services/stt).
// Contract:
//   GET/PUT /chat/api/v1/tts/config {enabled, default_voice, providers: [{provider, enabled, priority, config}]}
//   POST    /chat/api/v1/tts/providers {provider, enabled, priority, config} (one active provider)
//   GET/PUT /admin/chat/api/panel/tts/config  masked keys (a masked value is never written back)
//   GET/PUT /admin/chat/api/panel/stt/config  {active_provider, language, providers: {id: fields}}

export const MASK = "••••••••";

export type TtsProviderId = "openai" | "elevenlabs" | "aws_polly";
export type TtsOption = {
  id: TtsProviderId; label: string; keyField: string; secondKeyField?: string; voices: readonly string[];
  setting?: { key: string; label: string; choices?: readonly string[] };
};

export const TTS_PROVIDERS: readonly TtsOption[] = [
  { id: "openai", label: "OpenAI", keyField: "openai_api_key", voices: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
    setting: { key: "model", label: "Quality", choices: ["tts-1", "tts-1-hd"] } },
  { id: "elevenlabs", label: "ElevenLabs", keyField: "elevenlabs_api_key", voices: [],
    setting: { key: "model", label: "Model" } },
  { id: "aws_polly", label: "Amazon Polly", keyField: "aws_polly_access_key_id", secondKeyField: "aws_polly_secret_key",
    voices: ["Matthew", "Joanna", "Ivy", "Kendra", "Kimberly", "Salli", "Joey", "Justin", "Kevin", "Ruth", "Stephen",
      "Geraint", "Nicole", "Olivia", "Amy", "Emma"],
    setting: { key: "region", label: "Region" } },
];

export const QUALITY_LABELS: Record<string, string> = { "tts-1": "Standard", "tts-1-hd": "High definition" };
export const KEY_LABELS: Record<string, string> = {
  openai_api_key: "API key", elevenlabs_api_key: "API key", aws_polly_access_key_id: "Access key ID",
  aws_polly_secret_key: "Secret access key",
};

export type SttProviderId = "openai_whisper" | "local_whisper" | "aws_transcribe" | "azure_speech";
export const STT_PROVIDERS: readonly { id: SttProviderId; label: string; fields: readonly { key: string; label: string; secret?: boolean }[] }[] = [
  { id: "openai_whisper", label: "Whisper (OpenAI)", fields: [{ key: "api_key", label: "API key", secret: true }] },
  { id: "local_whisper", label: "Whisper (self-hosted)", fields: [
    { key: "base_url", label: "Server address" }, { key: "api_key", label: "API key (optional)", secret: true },
    { key: "model", label: "Model" }] },
  { id: "aws_transcribe", label: "Amazon Transcribe", fields: [
    { key: "access_key_id", label: "Access key ID", secret: true }, { key: "secret_access_key", label: "Secret access key", secret: true },
    { key: "region", label: "Region" }] },
  { id: "azure_speech", label: "Azure Speech", fields: [
    { key: "subscription_key", label: "Subscription key", secret: true }, { key: "region", label: "Region" }] },
];

export const LANGUAGES: readonly { value: string; label: string }[] = [
  { value: "", label: "Detect automatically" }, { value: "en-US", label: "English" }, { value: "de-DE", label: "German" },
  { value: "fr-FR", label: "French" }, { value: "it-IT", label: "Italian" },
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (typeof value === "string" ? value : "");

export type TtsState = { enabled: boolean; provider: TtsProviderId; voice: string; settings: Record<string, string>; keys: Record<string, string> };

export function readTts(config: unknown, keys: unknown): TtsState {
  const body = isRecord(config) ? config : {};
  const rows = Array.isArray(body.providers) ? body.providers.filter(isRecord) : [];
  const active = rows.find((row) => row.enabled === true) ?? rows.find((row) => TTS_PROVIDERS.some((p) => p.id === row.provider));
  const provider = (TTS_PROVIDERS.find((p) => p.id === active?.provider)?.id ?? "openai") as TtsProviderId;
  const rowConfig = isRecord(active?.config) ? active.config : {};
  return {
    enabled: body.enabled === true,
    provider,
    voice: str(body.default_voice),
    settings: Object.fromEntries(Object.entries(rowConfig).filter(([, value]) => typeof value === "string")) as Record<string, string>,
    keys: Object.fromEntries(Object.entries(isRecord(keys) ? keys : {}).map(([key, value]) => [key, str(value)])),
  };
}

/** The three writes of one save, each carrying everything it owns (a toggle never sends an empty config). */
export function ttsSaveBodies(state: TtsState, typedKeys: Record<string, string>) {
  const option = TTS_PROVIDERS.find((p) => p.id === state.provider) ?? TTS_PROVIDERS[0];
  const keys = Object.fromEntries(
    [option.keyField, option.secondKeyField].filter((field): field is string => Boolean(field))
      .map((field) => [field, (typedKeys[field] ?? "").trim()]).filter(([, value]) => value && value !== MASK),
  );
  const settings = Object.fromEntries(Object.entries(state.settings).filter(([, value]) => value.trim()));
  return {
    keys,
    provider: { provider: option.id, enabled: state.enabled, priority: 0, config: settings },
    config: { enabled: state.enabled, ...(state.voice ? { default_voice: state.voice } : {}) },
  };
}

export const hasKey = (state: TtsState, field: string) => state.keys[field] === MASK;

export function ttsReady(state: TtsState): boolean {
  if (!state.enabled) return false;
  const option = TTS_PROVIDERS.find((p) => p.id === state.provider);
  if (!option) return false;
  return hasKey(state, option.keyField) && (!option.secondKeyField || hasKey(state, option.secondKeyField));
}

export type SttState = { provider: SttProviderId | ""; language: string; fields: Record<string, Record<string, string>> };

export function readStt(payload: unknown): SttState {
  const body = isRecord(payload) ? payload : {};
  const providers = isRecord(body.providers) ? body.providers : {};
  const fields: Record<string, Record<string, string>> = {};
  for (const option of STT_PROVIDERS) {
    const raw = isRecord(providers[option.id]) ? providers[option.id] as Record<string, unknown> : {};
    fields[option.id] = Object.fromEntries(option.fields.map((field) => [field.key, str(raw[field.key])]));
  }
  const active = STT_PROVIDERS.find((option) => option.id === body.active_provider)?.id ?? "";
  return { provider: active, language: str(body.language), fields };
}

/** Only the chosen provider's typed values; a masked value is left out, never written back. */
export function sttSaveBody(state: SttState): Record<string, unknown> {
  const chosen = state.provider ? state.fields[state.provider] ?? {} : {};
  const values = Object.fromEntries(Object.entries(chosen).filter(([, value]) => value.trim() && value !== MASK));
  return {
    active_provider: state.provider || null, language: state.language,
    providers: state.provider ? { [state.provider]: values } : {},
  };
}
