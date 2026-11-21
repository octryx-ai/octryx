import type { SaveState } from "./useSpecStudio";

// The quiet save state of a section: "Saving…", "Saved", or the refusal in words with Retry.
export function SaveLine({ save }: { save?: SaveState }) {
  if (!save || save.state === "idle") return null;
  if (save.state === "failed") {
    return (
      <p className="studio-save studio-save--failed" role="alert">
        <span>Not saved: {save.message}</span>
        {save.retry ? <button type="button" className="ds-btn ds-btn--sm" onClick={save.retry}>Retry</button> : null}
      </p>
    );
  }
  return <p className="studio-save" role="status">{save.state === "saving" ? "Saving…" : "Saved"}</p>;
}
