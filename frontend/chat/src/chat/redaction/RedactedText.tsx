import "./redactedText.css";
import { redactionSegments } from "../transcripts/transcriptModel";

// A value as the server stored it, with every "[redacted]" marked so it reads as removed on purpose, never as
// content. The server masks secret-looking values in transcripts and in everything a model wrote: change
// previews, write plans, approval texts, REST call arguments. The UI never un-masks; it only shows the mark.
export function RedactedText({ value }: { value: string }) {
  return (
    <>
      {redactionSegments(value).map((segment, index) =>
        segment.redacted ? (
          <mark key={index} className="redacted-mark" title="Removed: a secret value or a credential's output">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}
