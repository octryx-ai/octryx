// File diff types and the diff folding helper of the skill catalog.
export type DiffLine = { kind: "same" | "added" | "removed"; text: string };
/** One file of `GET …/versions/{v}/diff`. */
export type FileDiff = { path: string; status: string; added: number; removed: number; lines: DiffLine[]; truncated: boolean };

export type DiffRow = { kind: DiffLine["kind"] | "hunk"; text: string };

/** Unchanged runs folded to `context` lines around each change. */
export function foldDiff(lines: DiffLine[], context = 2): DiffRow[] {
  const keep = new Set<number>();
  lines.forEach((line, index) => {
    if (line.kind === "same") return;
    for (let at = Math.max(0, index - context); at <= Math.min(lines.length - 1, index + context); at += 1) keep.add(at);
  });
  const rows: DiffRow[] = [];
  let skipped = 0;
  lines.forEach((line, index) => {
    if (!keep.has(index)) {
      skipped += 1;
      return;
    }
    if (skipped) rows.push({ kind: "hunk", text: `… ${skipped} unchanged line${skipped === 1 ? "" : "s"}` });
    skipped = 0;
    rows.push(line);
  });
  if (skipped) rows.push({ kind: "hunk", text: `… ${skipped} unchanged line${skipped === 1 ? "" : "s"}` });
  return rows;
}
