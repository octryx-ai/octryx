import { useEffect, useState } from "react";
import { EmptyLine } from "../../../layout/EmptyLine";
import { loadRevisionDiff } from "./documentApi";
import type { Loaded } from "./documentApi";
import { diffStatsText, sideBySide } from "./documentViewModel";
import type { DiffCell, DocumentDiff } from "./documentViewModel";
import type { DocumentRevision } from "./DocumentViewTab";

function Cell({ cell, side }: { cell: DiffCell; side: "left" | "right" }) {
  if (!cell) return <><td className="document-diff__no" /><td className={`document-diff__text document-diff__text--empty is-${side}`} /></>;
  return <>
    <td className="document-diff__no">{cell.line}</td>
    <td className={`document-diff__text is-${cell.kind}`} data-kind={cell.kind}>
      <span className="ds-visually-hidden">{cell.kind === "removed" ? "Removed: " : cell.kind === "added" ? "Added: " : ""}</span>
      {cell.text || " "}
    </td>
  </>;
}

// Two revisions side by side: the older left, the newer right, removed and added lines marked, "+12 −3" on top.
export function DocumentDiffTab({ workspaceId, sourceId, revisions }: {
  workspaceId: string; sourceId: string; revisions: DocumentRevision[];
}) {
  const ordered = [...revisions].sort((left, right) => right.revision_ordinal - left.revision_ordinal);
  const [toId, setToId] = useState(ordered[0]?.revision_id ?? "");
  const [fromId, setFromId] = useState(ordered[1]?.revision_id ?? "");
  const [loaded, setLoaded] = useState<Loaded<DocumentDiff> | null>(null);
  useEffect(() => {
    if (!fromId || !toId || fromId === toId) return undefined;
    let current = true;
    setLoaded(null);
    void loadRevisionDiff(workspaceId, sourceId, fromId, toId).then((next) => { if (current) setLoaded(next); });
    return () => { current = false; };
  }, [workspaceId, sourceId, fromId, toId]);

  if (ordered.length < 2) return <EmptyLine text="Only one revision so far; there is nothing to compare." testId="document-diff-single" />;
  const choice = (label: string, value: string, onChange: (next: string) => void) => (
    <label className="admin-panel__field document-diff__choice"><span>{label}</span>
      <select className="admin-panel__input" value={value} onChange={(event) => onChange(event.target.value)}>
        {ordered.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>Revision {revision.revision_ordinal}</option>)}
      </select>
    </label>
  );
  let body;
  if (fromId === toId) body = <EmptyLine text="Choose two different revisions." />;
  else if (!loaded) body = <p className="document-view__meta" role="status">Comparing…</p>;
  else if (!loaded.ok) body = <EmptyLine text={loaded.message} testId="document-diff-error" />;
  else if (loaded.data.state === "identical") body = <EmptyLine text="The two revisions have the same text." testId="document-diff-identical" />;
  else if (loaded.data.state === "too_large") body = <EmptyLine text="These revisions are too large to compare here." testId="document-diff-too-large" />;
  else {
    const rows = sideBySide(loaded.data.diff);
    body = <>
      <p className="document-view__meta" data-testid="document-diff-stats">{diffStatsText(loaded.data.stats)} lines</p>
      <div className="document-diff__wrap">
        <table className="document-diff" data-testid="document-diff-table">
          <thead><tr>
            <th colSpan={2} scope="colgroup">Revision {loaded.data.from?.revision_ordinal ?? ""}</th>
            <th colSpan={2} scope="colgroup">Revision {loaded.data.to?.revision_ordinal ?? ""}</th>
          </tr></thead>
          <tbody>{rows.map((row, index) => row.hunk
            ? <tr key={index} className="document-diff__hunk"><td colSpan={4}>{row.hunk}</td></tr>
            : <tr key={index}><Cell cell={row.left} side="left" /><Cell cell={row.right} side="right" /></tr>)}</tbody>
        </table>
      </div>
    </>;
  }
  return <div className="document-diff__tab">
    <div className="document-diff__choices">{choice("Older", fromId, setFromId)}{choice("Newer", toId, setToId)}</div>
    {body}
  </div>;
}
