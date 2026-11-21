import { useCallback, useEffect, useState } from "react";

import { CustomDetectorDrawer } from "./CustomDetectorDrawer";
import { loadDetectorCatalog } from "./detectorsApi";
import { filterDetectors, maskLabel, readDetectorCatalog, sourceLabel } from "./detectorsModel";
import type { DetectorCatalog, DetectorRow } from "./detectorsModel";
import type { EditTarget } from "./policyCatalogModel";
import { refusalText } from "./policyEngineVersions";
import "./detectors.css";

type Drawer = { row: DetectorRow | null } | null;

// Settings → Governance → Policies → Detectors: built-in and custom detectors with their category, how
// they decide, confidence, mask, the policies that use them and where they come from. Custom rows open the
// detector drawer; "+ Custom detector" adds one to the draft (same edit target as a policy edit).
export function AdminDetectors({ target, workspaces, onSaved, previewDelay, onEditElsewhere }: {
  target: EditTarget | null;
  workspaces: { id: string; name: string }[];
  onSaved: (text: string) => Promise<void>;
  previewDelay?: number;
  // The editor lives in Content security; Policies shows the list read-only with this link.
  onEditElsewhere?: () => void;
}) {
  const [catalog, setCatalog] = useState<DetectorCatalog | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [drawer, setDrawer] = useState<Drawer>(null);

  const load = useCallback(async () => {
    try {
      setCatalog(readDetectorCatalog(await loadDetectorCatalog()));
      setProblem(null);
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, []);
  // The edit target's digest changes with every draft save, so the "used by" counts follow policy edits too.
  useEffect(() => { void load(); }, [load, target?.digest]);

  if (problem) return <p className="workspace-classification__message" role="alert" data-testid="detectors-error">{problem}</p>;
  if (!catalog) return <p className="admin-panel__hint" role="status">Loading the detectors…</p>;

  const workspaceName = (id: string) => workspaces.find((item) => item.id === id)?.name ?? id;
  const categoryName = (id: string) => catalog.categories.find((item) => item.id === id)?.label ?? id;
  const rows = filterDetectors(catalog.detectors, query, category);
  const saved = async (text: string) => { setDrawer(null); await onSaved(text); await load(); };

  return (
    <div data-testid="detectors">
      <div className="policies__toolbar">
        <input className="admin-users__toolbar-input" placeholder="Search detectors …" value={query} data-testid="detectors-search" onChange={(event) => setQuery(event.target.value)} />
        <select className="admin-users__toolbar-select" value={category} data-testid="detectors-filter-category" onChange={(event) => setCategory(event.target.value)}>
          <option value="">All categories</option>
          {catalog.categories.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.id})</option>)}
        </select>
        <span className="policies__spacer" />
        {onEditElsewhere ? (
          <button type="button" className="admin-panel__action-btn" data-testid="detectors-edit-elsewhere" onClick={onEditElsewhere}>
            Edit in Content security
          </button>
        ) : (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="detectors-new"
            disabled={!target} title={!target ? "The draft is in review and frozen." : undefined} onClick={() => setDrawer({ row: null })}>+ Custom detector</button>
        )}
      </div>
      <table className="admin-panel__table" data-testid="detectors-table">
        <thead><tr><th scope="col">Detector</th><th scope="col">Category</th><th scope="col">How it decides</th><th scope="col">Confidence</th><th scope="col">Mask</th><th scope="col">Used by</th><th scope="col">Source</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} data-testid="detector-row" className={row.custom && !onEditElsewhere ? "policies__table-row" : undefined}
              onClick={row.custom && !onEditElsewhere ? () => setDrawer({ row }) : undefined}>
              <td><div className="policies__name">{row.label}</div><div className="policies__sub"><span className="admin-policy-inline-code">{row.id}</span></div></td>
              <td>{categoryName(row.category)}</td>
              <td className="policies__summary">{row.method}</td>
              <td><span className={`work-badge work-badge--${row.confidence.startsWith("high") ? "active" : "neutral"}`} title={row.confidence}>{row.confidence.split(":")[0]}</span></td>
              <td className="admin-panel__cell--muted">{row.maskStyles.length ? maskLabel(row.maskStyles[0]) : "—"}</td>
              <td className="admin-panel__cell--muted" title={row.usedBy.join(", ") || undefined}>{row.usedBy.length} {row.usedBy.length === 1 ? "policy" : "policies"}</td>
              <td>{row.custom ? <span className="work-badge work-badge--attention">{sourceLabel(row, catalog.state, workspaceName)}</span> : <span className="policies__src">Built-in</span>}</td>
            </tr>
          ))}
          {!rows.length ? <tr><td colSpan={7}><div className="admin-panel__empty-state" data-testid="detectors-empty">No detectors match. Clear the filters.</div></td></tr> : null}
        </tbody>
      </table>
      <p className="admin-panel__hint policies__table-hint">
        Detectors only <b>find</b>; policies decide what happens. Custom detectors are part of the policy set: they are saved into the draft,
        reviewed by a second admin and published with it. Patterns run on RE2 (linear time) and are capped at 300 characters; try one in the
        drawer&apos;s Test field with synthetic text — the test text is never stored.
      </p>
      {drawer ? (
        <CustomDetectorDrawer row={drawer.row} catalog={catalog} target={target} workspaces={workspaces} previewDelay={previewDelay}
          onClose={() => setDrawer(null)} onSaved={saved} />
      ) : null}
    </div>
  );
}
