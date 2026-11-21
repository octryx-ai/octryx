// Workspace TTS fields: provider, default voice and speed selects shown when TTS is enabled.
import type { TtsProvider } from "./projectVoiceTypes";

const VOICE_OPTIONS = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"];
const SPEED_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0];

type ProjectVoiceTtsFieldsProps = {
  ttsProvider: string;
  setTtsProvider: (value: string) => void;
  ttsVoice: string;
  setTtsVoice: (value: string) => void;
  ttsSpeed: number;
  setTtsSpeed: (value: number) => void;
  hasAnyProvider: boolean;
  installedProviders: TtsProvider[];
  providerVoices: string[];
};

export function ProjectVoiceTtsFields({
  ttsProvider, setTtsProvider, ttsVoice, setTtsVoice, ttsSpeed, setTtsSpeed,
  hasAnyProvider, installedProviders, providerVoices,
}: ProjectVoiceTtsFieldsProps) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: "0.75rem",
      }}
    >
      <div className="admin-form-field">
        <label className="admin-form-field__label">Provider</label>
        <select
          className="user-edit-panel__select"
          value={ttsProvider}
          onChange={(e) => setTtsProvider(e.target.value)}
        >
          {!hasAnyProvider && (
            <option value="openai">
              OpenAI (not configured globally)
            </option>
          )}
          {installedProviders.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {!hasAnyProvider && (
          <p
            className="admin-panel__hint"
            style={{ fontSize: "var(--ds-text-xs)", marginTop: "0.25rem" }}
          >
            No voice provider is configured yet. Add credentials under
            Runtime → Voice.
          </p>
        )}
      </div>

      {providerVoices.length > 0 && (
        <div className="admin-form-field">
          <label className="admin-form-field__label">Default voice</label>
          <select
            className="user-edit-panel__select"
            value={ttsVoice}
            onChange={(e) => setTtsVoice(e.target.value)}
          >
            {(providerVoices.length ? providerVoices : VOICE_OPTIONS).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="admin-form-field">
        <label className="admin-form-field__label">Speed</label>
        <select
          className="user-edit-panel__select"
          value={ttsSpeed}
          onChange={(e) => setTtsSpeed(Number(e.target.value))}
        >
          {SPEED_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}x
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
