import { diffLines } from "./promptCatalogModel";
import type { PromptDiff } from "./promptCatalogTypes";

// The unified diff of a version against the body it would replace at its scope.
export function PromptDiffView({ diff, onClose }: { diff: PromptDiff; onClose: () => void }) {
  return (
    <div className="ws-section" data-testid="pc-diff">
      <div className="admin-panel__section-header">
        <span>Diff against {diff.baseline}</span>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>
          Close diff
        </button>
      </div>
      {diff.identical ? (
        <span className="ws-muted">Identical to the body it would replace.</span>
      ) : (
        <pre className="pc-diff">
          {diffLines(diff.diff).map((line, index) => (
            <span key={index} className={`pc-diff__line pc-diff__line--${line.kind}`}>
              {line.text}
              {"\n"}
            </span>
          ))}
        </pre>
      )}
    </div>
  );
}
