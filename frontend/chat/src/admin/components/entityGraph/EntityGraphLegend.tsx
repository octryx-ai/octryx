// The legend is the type filter: one chip per entity type with its colour and count. A click hides or shows the
// type; a double-click (or Alt-click) shows that type alone, again to show all. Nothing is laid out again.
// At most two rows of chips; the rest wait under "+N more" (measured, so it follows the legend's width).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { LegendItem } from "./kgView";
import { slotColor } from "./kgView";

type Props = {
  items: LegendItem[];
  onToggle: (type: string) => void;
  onOnly: (type: string) => void;
  onShowAll: () => void;
  // Shown instead of a one-chip legend ("Entity types are not classified for this workspace."), or above the chips
  // when they are groups by connection rather than types.
  note?: string;
  // "groups": the chips are structure groups, not entity types.
  kind?: "types" | "groups";
};

const MAX_ROWS = 2;

export function EntityGraphLegend({ items, onToggle, onOnly, onShowAll, note, kind = "types" }: Props) {
  const box = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  // How many chips fit in two rows with "+N more"; null while measuring (all chips drawn).
  const [cut, setCut] = useState<number | null>(null);
  const shape = items.map((item) => item.type).join("|");
  useEffect(() => { setCut(null); }, [shape]);
  useEffect(() => {
    const element = box.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    let width = element.clientWidth;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth !== width) { width = element.clientWidth; setCut(null); }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    if (expanded || cut !== null || !box.current) return;
    const chips = Array.from(box.current.querySelectorAll<HTMLElement>('[data-testid="kg-legend-chip"]'));
    const rows = Array.from(new Set(chips.map((chip) => chip.offsetTop))).sort((a, b) => a - b);
    if (rows.length <= MAX_ROWS || typeof rows[0] !== "number") { setCut(chips.length); return; }
    const fit = chips.filter((chip) => chip.offsetTop <= rows[MAX_ROWS - 1]).length;
    setCut(Math.max(1, fit - 1));
  }, [expanded, cut, shape]);
  if (items.length < 2) return note ? <p className="kg-legend kg-legend__note">{note}</p> : null;
  const anyHidden = items.some((item) => item.hidden);
  const shown = expanded || cut === null ? items : items.slice(0, cut);
  const more = items.length - shown.length;
  const what = kind === "groups" ? "Groups" : "Entity types";
  return <div ref={box} className="kg-legend" role="group" aria-label={`${what}: click to hide or show, double-click to show one only`}>
    {note && kind === "groups" ? <p className="kg-legend__note kg-legend__note--row">{note}</p> : null}
    {shown.map((item) => <button key={item.type} type="button" className="kg-legend__chip" data-testid="kg-legend-chip"
      data-type={item.type} aria-pressed={!item.hidden} title={`${item.type}: click to ${item.hidden ? "show" : "hide"}, double-click for this type only`}
      onClick={(event) => (event.altKey ? onOnly(item.type) : onToggle(item.type))}
      onDoubleClick={() => onOnly(item.type)}>
      <span className="kg-legend__dot" style={{ background: slotColor(item.slot) }} aria-hidden="true" />
      <span className="kg-legend__name">{item.type}</span>
      <span className="kg-legend__count">{item.total}</span>
    </button>)}
    {more > 0 ? <button type="button" className="kg-legend__all" aria-expanded="false" onClick={() => setExpanded(true)}>
      +{more} more</button> : null}
    {expanded && cut !== null && cut < items.length ? <button type="button" className="kg-legend__all" aria-expanded="true"
      onClick={() => setExpanded(false)}>Show fewer</button> : null}
    {anyHidden ? <button type="button" className="kg-legend__all" onClick={onShowAll}>Show all</button> : null}
  </div>;
}
