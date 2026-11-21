import type { Dispatch, SetStateAction } from "react";

import "../modelCatalog/modelCatalog.css";
import {
  KEY_LABELS,
  LANGUAGES,
  MASK,
  QUALITY_LABELS,
  STT_PROVIDERS,
  TTS_PROVIDERS,
  hasKey,
  ttsReady,
} from "./voiceContract";
import type { SttProviderId, SttState, TtsProviderId, TtsState } from "./voiceContract";
import { LoadingState } from "../../../layout/LoadingState";
import { playVoiceTest, saveVoiceSettings, useVoiceSettings } from "./useVoiceSettings";

type TtsCardProps = {
  tts: TtsState;
  setTts: Dispatch<SetStateAction<TtsState | null>>;
  typedKeys: Record<string, string>;
  setTypedKeys: Dispatch<SetStateAction<Record<string, string>>>;
};

// A key of the chosen TTS provider: never shown, only typed; "stored" when one is saved.
function TtsKeyField({ field, tts, typedKeys, setTypedKeys }: Omit<TtsCardProps, "setTts"> & { field: string }) {
  return (
    <label className="admin-panel__field">
      <span>{KEY_LABELS[field] ?? field}{hasKey(tts, field) ? " (stored ✓)" : ""}</span>
      <input type="password" autoComplete="off" value={typedKeys[field] ?? ""} aria-label={KEY_LABELS[field] ?? field}
        onChange={(event) => setTypedKeys((current) => ({ ...current, [field]: event.target.value }))} />
    </label>
  );
}

// The TTS provider, its voice, its one setting and its keys.
function TtsFields({ tts, setTts, typedKeys, setTypedKeys }: TtsCardProps) {
  const option = TTS_PROVIDERS.find((item) => item.id === tts.provider) ?? TTS_PROVIDERS[0];
  const setTtsPatch = (patch: Partial<TtsState>) => setTts((current) => (current ? { ...current, ...patch } : current));
  const setting = (key: string, value: string) => setTtsPatch({ settings: { ...tts.settings, [key]: value } });
  return (
    <>
      <label className="admin-panel__field">
        <span>Provider</span>
        <select value={tts.provider} data-testid="tts-provider"
          onChange={(event) => setTtsPatch({ provider: event.target.value as TtsProviderId, voice: "", settings: {} })}>
          {TTS_PROVIDERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Voice</span>
        {option.voices.length ? (
          <select value={tts.voice} onChange={(event) => setTtsPatch({ voice: event.target.value })} data-testid="tts-voice">
            <option value="">Provider default</option>
            {option.voices.map((voice) => <option key={voice} value={voice}>{voice}</option>)}
          </select>
        ) : (
          <input value={tts.voice} onChange={(event) => setTtsPatch({ voice: event.target.value })} aria-label="Voice" />
        )}
      </label>
      {option.setting ? (
        <label className="admin-panel__field">
          <span>{option.setting.label}</span>
          {option.setting.choices ? (
            <select value={tts.settings[option.setting.key] ?? option.setting.choices[0]}
              onChange={(event) => setting(option.setting!.key, event.target.value)} data-testid="tts-setting">
              {option.setting.choices.map((choice) => <option key={choice} value={choice}>{QUALITY_LABELS[choice] ?? choice}</option>)}
            </select>
          ) : (
            <input value={tts.settings[option.setting.key] ?? ""} aria-label={option.setting.label}
              onChange={(event) => setting(option.setting!.key, event.target.value)} />
          )}
        </label>
      ) : null}
      <TtsKeyField key={option.keyField} field={option.keyField} tts={tts} typedKeys={typedKeys} setTypedKeys={setTypedKeys} />
      {option.secondKeyField ? (
        <TtsKeyField key={option.secondKeyField} field={option.secondKeyField} tts={tts} typedKeys={typedKeys}
          setTypedKeys={setTypedKeys} />
      ) : null}
    </>
  );
}

function TtsCard(props: TtsCardProps) {
  const { tts } = props;
  const setTtsPatch = (patch: Partial<TtsState>) => props.setTts((current) => (current ? { ...current, ...patch } : current));
  return (
    <div className="admin-panel__card">
      <div className="model-catalog__bar">
        <div className="admin-panel__section-header"><span>Text to speech</span></div>
        <span className={`work-badge work-badge--${ttsReady(tts) ? "active" : "attention"}`}>
          {ttsReady(tts) ? "Ready" : tts.enabled ? "Needs a key" : "Off"}
        </span>
      </div>
      <div className="admin-panel__form-grid">
        <TtsFields {...props} />
      </div>
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={tts.enabled} onChange={(event) => setTtsPatch({ enabled: event.target.checked })}
          data-testid="tts-enabled" />
        Text to speech is on
      </label>
    </div>
  );
}

function SttCard({ stt, setStt }: { stt: SttState; setStt: Dispatch<SetStateAction<SttState | null>> }) {
  const sttOption = STT_PROVIDERS.find((item) => item.id === stt.provider);
  return (
    <div className="admin-panel__card">
      <div className="model-catalog__bar">
        <div className="admin-panel__section-header"><span>Speech to text</span></div>
        <span className={`work-badge work-badge--${stt.provider ? "active" : "attention"}`}>{stt.provider ? "Configured" : "Off"}</span>
      </div>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Provider</span>
          <select value={stt.provider} data-testid="stt-provider"
            onChange={(event) => setStt({ ...stt, provider: event.target.value as SttProviderId | "" })}>
            <option value="">None</option>
            {STT_PROVIDERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Language</span>
          <select value={stt.language} onChange={(event) => setStt({ ...stt, language: event.target.value })}>
            {LANGUAGES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
        {sttOption?.fields.map((field) => (
          <label key={field.key} className="admin-panel__field">
            <span>{field.label}{field.secret && stt.fields[sttOption.id]?.[field.key] === MASK ? " (stored ✓)" : ""}</span>
            <input type={field.secret ? "password" : "text"} autoComplete="off" aria-label={field.label}
              value={stt.fields[sttOption.id]?.[field.key] === MASK ? "" : stt.fields[sttOption.id]?.[field.key] ?? ""}
              onChange={(event) => setStt({ ...stt, fields: { ...stt.fields,
                [sttOption.id]: { ...stt.fields[sttOption.id], [field.key]: event.target.value } } })} />
          </label>
        ))}
      </div>
      <p className="model-catalog__sub">Used by Teams calling and call recordings.</p>
    </div>
  );
}

// Runtime → Capabilities → Voice & speech: text to speech and speech to text with
// only the providers the backend builds. Every visible field round-trips; turning speech on or off keeps its settings.
export function AdminVoiceAndSpeech() {
  const voice = useVoiceSettings();
  const { tts, setTts, typedKeys, setTypedKeys, stt, setStt, message, setMessage, saving } = voice;

  if (!tts || !stt) {
    return message ? <p className="admin-panel__error" role="alert">{message.text}</p>
      : <LoadingState label="voice settings" variant="page" />;
  }

  return (
    <div className="model-catalog" data-testid="voice-and-speech">
      <TtsCard tts={tts} setTts={setTts} typedKeys={typedKeys} setTypedKeys={setTypedKeys} />
      <SttCard stt={stt} setStt={setStt} />
      {message ? (
        <p className={message.error ? "admin-panel__error" : "admin-panel__success"} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      ) : null}
      <div className="model-catalog__row-group">
        <button type="button" className="admin-panel__action-btn" onClick={() => void playVoiceTest(setMessage)}>Play a test sentence</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={saving}
          data-testid="voice-save" onClick={() => void saveVoiceSettings(voice)}>
          {saving ? "Saving…" : "Save voice & speech"}
        </button>
      </div>
    </div>
  );
}
