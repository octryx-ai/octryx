import { foldDiff, type DiffRow, type FileDiff } from "./skillDiffModel";

// A per-file line diff from `GET …/versions/{v}/diff` (`lines: [{kind: same|added|removed, text}]`), with unchanged
// runs folded to two context lines around each change.
const CLASSES: Record<DiffRow["kind"], string> = { same: "", added: "add", removed: "del", hunk: "hunk" };
const PREFIX: Record<DiffRow["kind"], string> = { same: "  ", added: "+ ", removed: "- ", hunk: "" };

export function SkillDiff({ file, maxHeight }: { file: FileDiff; maxHeight?: string }) {
  if (file.status === "unchanged") return <p className="skills__hint">{file.path}: unchanged.</p>;
  return (
    <div className="skills__diff" style={maxHeight ? { maxHeight } : undefined} data-testid={`skill-diff-${file.path}`}>
      {foldDiff(file.lines).map((row, index) => (
        <div key={index} className={CLASSES[row.kind]}>{PREFIX[row.kind]}{row.text}</div>
      ))}
      {file.truncated ? <div className="hunk">… diff truncated</div> : null}
    </div>
  );
}
