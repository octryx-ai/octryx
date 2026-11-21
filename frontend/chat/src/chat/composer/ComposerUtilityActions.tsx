import { AttachIcon, MentionIcon, SlashCommandIcon, VoiceInputIcon } from "../composerIcons";
import type { ComposerShellProps } from "../composerShellTypes";

export type ComposerUtilityActionsProps = Pick<
  ComposerShellProps,
  | "composerDisabled"
  | "uploadingAttachments"
  | "fileInputRef"
  | "sttAvailable"
  | "sttListening"
  | "startSTT"
  | "selectedSession"
  | "showCanvas"
  | "openCanvas"
> & {
  insertComposerToken: (token: string) => void;
  showAttach: boolean;
};

export function ComposerAttachButton({
  composerDisabled,
  uploadingAttachments,
  fileInputRef,
}: Pick<
  ComposerShellProps,
  "composerDisabled" | "uploadingAttachments" | "fileInputRef"
>) {
  return (
    <button
      type="button"
      className="composer-action-button composer-action-button--icon composer-action-button--ghost composer-action-button--attach"
      disabled={composerDisabled || uploadingAttachments}
      title="Attach files"
      aria-label="Attach files"
      onClick={() => fileInputRef.current?.click()}
    >
      <AttachIcon />
    </button>
  );
}

// Attach / slash / mention / voice. `showAttach` is false inside the compact
// composer disclosure, where attaching stays a primary control next to send. The drawing canvas is not an ordinary
// chat entry.
export function ComposerUtilityActions({
  composerDisabled,
  uploadingAttachments,
  fileInputRef,
  sttAvailable,
  sttListening,
  startSTT,
  insertComposerToken,
  showAttach,
}: ComposerUtilityActionsProps) {
  return (
    <div className="composer__utility-actions" aria-label="Composer utilities">
      {showAttach ? (
        <ComposerAttachButton
          composerDisabled={composerDisabled}
          uploadingAttachments={uploadingAttachments}
          fileInputRef={fileInputRef}
        />
      ) : null}
      <button
        type="button"
        className="composer-action-button composer-action-button--icon composer-action-button--ghost"
        disabled={composerDisabled}
        title="Insert slash command"
        aria-label="Insert slash command"
        onClick={() => insertComposerToken("/")}
      >
        <SlashCommandIcon />
      </button>
      <button
        type="button"
        className="composer-action-button composer-action-button--icon composer-action-button--ghost"
        disabled={composerDisabled}
        title="Mention agent or file"
        aria-label="Mention agent or file"
        onClick={() => insertComposerToken("@")}
      >
        <MentionIcon />
      </button>
      {sttAvailable ? (
        <button
          type="button"
          className={`composer-action-button composer-action-button--icon composer-action-button--ghost ${sttListening ? "composer-action-button--active" : ""}`}
          onClick={() => void startSTT()}
          title={
            sttListening
              ? "Click to stop recording"
              : "Voice input (Whisper / Browser)"
          }
          aria-label={sttListening ? "Stop voice recording" : "Voice input"}
        >
          <VoiceInputIcon />
        </button>
      ) : null}
    </div>
  );
}
