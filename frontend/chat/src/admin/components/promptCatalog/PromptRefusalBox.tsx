import type { PromptRefusal } from "./promptCatalogModel";

// A refusal in plain words only (run texts brief: never raw codes); the code stays on the element for support.
export function PromptRefusalBox({ refusal }: { refusal: PromptRefusal | null }) {
  if (!refusal) return null;
  return (
    <div className="ws-alert ws-alert--error" role="alert" data-refusal-code={refusal.code}>
      <span>{refusal.text}</span>
    </div>
  );
}
