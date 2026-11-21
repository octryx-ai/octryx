import { useState, type ReactNode } from "react";

import { shortCommit } from "./skillCatalogModel";
import type { Conflict, MergeReport, Resolution } from "./skillCatalogTypes";
import { lineText, markChanged, resolutionIssue, resolutionLabel, type MarkedLine } from "./skillUpdateModel";

// One merge conflict of an upstream update draft (mock `renderUpdate`): upstream before / yours / upstream
// now side by side with the local lines highlighted, the relocation suggestion when upstream moved the block into
// another file, and the resolution choices. A choice is saved at once by the parent (PUT …/versions/{v}).
export function SkillConflictCard({ conflict, report, resolution, editable, busy, onResolve }: {
  conflict: Conflict;
  report: MergeReport;
  resolution: Resolution | undefined;
  editable: boolean;
  busy: boolean;
  onResolve: (resolution: Resolution) => Promise<boolean>;
}) {
  const [manual, setManual] = useState<string | null>(resolution?.choice === "manual" ? resolution.text ?? "" : null);
  const [issue, setIssue] = useState<string | null>(null);
  const relocation = conflict.relocation;
  const choice = manual !== null ? "manual" : resolution?.choice;

  const pick = async (next: Resolution) => {
    const problem = resolutionIssue(next, conflict);
    setIssue(problem);
    if (problem) return;
    if (await onResolve(next) && next.choice !== "manual") setManual(null);
  };
  const option = (value: Resolution["choice"], title: string, text: string, onClick: () => void) => (
    <button type="button" className={`policies__choice${choice === value ? " policies__choice--selected" : ""}`}
      data-testid={`skill-conflict-choice-${value}`} disabled={!editable || busy} onClick={onClick}>
      <b>{title}</b><span>{text}</span>
    </button>
  );

  return (
    <div className="skills__conflict" data-testid={`skill-conflict-${conflict.id}`}>
      <div className="policies__row">
        <span className={`work-badge work-badge--${resolution ? "active" : "attention"}`}>{resolution ? "Resolved" : "Conflict"}</span>
        <b className="skills__mono">{conflict.path}</b>
        <span className="skills__hint">
          {resolution ? resolutionLabel(resolution, conflict) : conflict.kind === "file"
            ? "the file was changed on one side and removed on the other"
            : "you and upstream changed the same lines"}
        </span>
      </div>
      <ThreeWay conflict={conflict} report={report} />
      <div className="policies__choice-grid" style={{ gridTemplateColumns: `repeat(${relocation ? 4 : 3},minmax(0,1fr))` }}>
        {relocation ? option("relocate", "Apply my change in the new place",
          `Apply my change in ${relocation.path}: your lines replace lines ${relocation.line}–${relocation.end_line} there.`,
          () => void pick({ choice: "relocate" })) : null}
        {option("upstream", "Take upstream", "Drop your customization here; the lines stay as upstream wrote them.",
          () => void pick({ choice: "upstream" }))}
        {option("mine", "Keep mine", "Keep your lines in place of the upstream change.", () => void pick({ choice: "mine" }))}
        {option("manual", "Edit by hand", "Write the merged lines yourself.",
          () => setManual(manual ?? (resolution?.choice === "manual" ? resolution.text ?? "" : conflict.ours.join(""))))}
      </div>
      {manual !== null && editable ? (
        <ManualMerge path={conflict.path} manual={manual} busy={busy} setManual={setManual}
          onSave={() => void pick({ choice: "manual", text: manual })} onCancel={() => { setManual(null); setIssue(null); }} />
      ) : null}
      {issue ? <p className="workspace-classification__message" role="alert">{issue}</p> : null}
    </div>
  );
}

// Upstream before, yours and upstream now side by side, with where upstream moved the block when it did.
function ThreeWay({ conflict, report }: { conflict: Conflict; report: MergeReport }) {
  const relocation = conflict.relocation;
  return (
    <div className="skills__3way">
      <div>
        <h4>Upstream before · {shortCommit(report.base_commit)}</h4>
        <LineBlock lines={conflict.base.map((text) => ({ text: lineText(text), mark: "" }))} />
      </div>
      <div>
        <h4>Yours{report.from_version ? ` · v${report.from_version}` : ""}</h4>
        <LineBlock lines={markChanged(conflict.base, conflict.ours, "loc")} />
      </div>
      <div>
        <h4>Upstream now · {shortCommit(report.theirs_commit)}</h4>
        <LineBlock lines={markChanged(conflict.base, conflict.theirs, "add")}
          after={relocation ? (
            <>
              <div className="hunk">Upstream moved this block to {relocation.path}:{relocation.line}–{relocation.end_line}</div>
              {relocation.block.map((text, index) => <div key={index} className="add">{lineText(text)}</div>)}
            </>
          ) : null} />
      </div>
    </div>
  );
}

// The merged lines written by hand, saved as the resolution or dropped.
function ManualMerge({ path, manual, busy, setManual, onSave, onCancel }: {
  path: string; manual: string; busy: boolean; setManual: (text: string) => void; onSave: () => void; onCancel: () => void;
}) {
  return (
    <div className="admin-panel__stack">
      <label className="admin-panel__field"><span>Merged text for {path}</span>
        <textarea className="skills__textarea" style={{ minHeight: "8rem" }} value={manual} data-testid="skill-conflict-manual"
          onChange={(event) => setManual(event.target.value)} /></label>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
          data-testid="skill-conflict-manual-save" onClick={onSave}>Save merged text</button>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function LineBlock({ lines, after }: { lines: MarkedLine[]; after?: ReactNode }) {
  return (
    <div className="skills__diff">
      {lines.length ? lines.map((line, index) => <div key={index} className={line.mark}>{line.text || " "}</div>) : <div className="hunk">(no lines)</div>}
      {after}
    </div>
  );
}
