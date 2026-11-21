// Workspace voice settings section: load, toggle and save TTS and STT usage for one Workspace.
import { useAdminNavigation } from "../../adminNavigation";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { ProjectVoiceToggleCard } from "./ProjectVoiceToggleCard";
import { ProjectVoiceTtsFields } from "./ProjectVoiceTtsFields";
import { useProjectVoiceSettings } from "./useProjectVoiceSettings";

type ProjectVoiceSectionProps = {
  ctx: Record<string, unknown>;
};

function VoiceSaveStatus({ error, saved }: { error: string | null; saved: boolean }) {
  return (
    <>
      {error && (
        <div className="admin-panel__error" style={{ marginBottom: "0.75rem" }}>
          {error}
        </div>
      )}
      {saved && (
        <div
          style={{
            background: "rgba(74,222,128,0.08)",
            color: "var(--status-active)",
            padding: "0.4rem 0.8rem",
            borderRadius: "var(--ds-radius-md)",
            fontSize: "var(--ds-text-xs)",
            marginBottom: "0.75rem",
          }}
        >
          Saved successfully!
        </div>
      )}
    </>
  );
}

function VoiceSectionIntro({ projectName, openVoiceTab }: { projectName: string; openVoiceTab: () => void }) {
  return (
    <>
      <div
        className="admin-panel__section-header"
        style={{ marginBottom: "1rem" }}
      >
        <span>Voice configuration</span>
        <span style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" }}>
          Project: <strong>{projectName}</strong>
        </span>
      </div>

      <p className="admin-panel__hint" style={{ marginBottom: "1.25rem" }}>
        Configure text-to-speech (TTS) and speech-to-text (STT) for this
        workspace. Provider credentials are managed once under Runtime → Voice;
        only usage settings are workspace-specific.{" "}
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={openVoiceTab}
        >
          Open Runtime → Voice
        </button>
      </p>
    </>
  );
}

export function ProjectVoiceSection({ ctx }: ProjectVoiceSectionProps) {
  const { configuringProjectQuality, readJson } = ctx as Record<string, unknown>;

  const project = configuringProjectQuality as AdminProjectQuality | null;
  const { openAdminTab } = useAdminNavigation();
  const voice = useProjectVoiceSettings(project?.id, readJson);
  const { ttsEnabled, setTtsEnabled, sttEnabled, setSttEnabled, globalTts, saving } = voice;

  if (!project) return null;

  const installedProviders =
    globalTts?.providers?.filter((p) => p.installed) ?? [];
  const hasAnyProvider = installedProviders.length > 0;
  const selectedProviderMeta = globalTts?.providers?.find(
    (p) => p.id === voice.ttsProvider,
  );
  const providerVoices = selectedProviderMeta?.voices ?? [];

  return (
    <div>
      <VoiceSectionIntro projectName={project.name} openVoiceTab={() => openAdminTab("tts")} />

      <ProjectVoiceToggleCard
        title="Text-to-Speech (TTS)"
        status={ttsEnabled ? "Active — agents can synthesize speech for this project" : "Disabled for this project"}
        enabled={ttsEnabled}
        onToggle={() => setTtsEnabled((v) => !v)}
        headGap="0.85rem"
      >
        {ttsEnabled && (
          <ProjectVoiceTtsFields
            ttsProvider={voice.ttsProvider} setTtsProvider={voice.setTtsProvider}
            ttsVoice={voice.ttsVoice} setTtsVoice={voice.setTtsVoice}
            ttsSpeed={voice.ttsSpeed} setTtsSpeed={voice.setTtsSpeed}
            hasAnyProvider={hasAnyProvider} installedProviders={installedProviders}
            providerVoices={providerVoices}
          />
        )}
      </ProjectVoiceToggleCard>

      <ProjectVoiceToggleCard
        title="Speech-to-Text (STT)"
        status={sttEnabled ? "Active — voice input enabled for this project" : "Disabled for this project"}
        enabled={sttEnabled}
        onToggle={() => setSttEnabled((v) => !v)}
      />

      <VoiceSaveStatus error={voice.error} saved={voice.saved} />
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={saving}
        onClick={() => void voice.handleSave()}
      >
        {saving ? "Saving…" : "Save Voice Settings"}
      </button>
    </div>
  );
}
