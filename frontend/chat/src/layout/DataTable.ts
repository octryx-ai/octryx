import { createElement, useRef, type KeyboardEvent, type ReactElement, type ReactNode } from "react";

import { EmptyLine, type EmptyLineProps } from "./EmptyLine";
import { LoadingState } from "./LoadingState";

// The one list of the design system: a full-width table with compact rows (36 px), a sticky header and keyboard
// navigation. A row opens its detail (usually a SidePanel) by click or Enter; arrow keys move between rows. The row
// "⋯" menu is passed in by the page (rowMenu, e.g. the existing ActionMenu with row={{objectName}}), so this file
// stays loadable by the unit-test loaders.

export type DataTableColumn<Row> = {
  key: string;
  header: string;
  render: (row: Row) => ReactNode;
  // "grow" takes the remaining width; "nowrap" keeps dates and ids on one line; "end" aligns numbers right.
  width?: string;
  grow?: boolean;
  nowrap?: boolean;
  // A long text on one line, cut with "…" at this width (e.g. "16rem"); the full text belongs in the cell's title.
  // It keeps the table inside the page at 1280 px instead of pushing the last columns out.
  clip?: string;
  // The narrowest the column may become while another column grows (e.g. a name that must stay readable).
  minWidth?: string;
  align?: "start" | "end";
};

export type DataTableProps<Row> = {
  // Accessible name of the table ("Pull requests").
  label: string;
  columns: DataTableColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  // Opens the row's detail; without it rows are not interactive.
  onOpen?: (row: Row) => void;
  // The row shown in the open side panel.
  selectedKey?: string | null;
  // The row "⋯" menu (rendered in the last cell; clicks inside it do not open the row).
  rowMenu?: (row: Row) => ReactNode;
  loading?: boolean;
  // What is loading, for the shared loading state ("pull requests").
  loadingLabel?: string;
  onRetry?: () => void;
  empty?: EmptyLineProps;
  testId?: string;
};

/** The row index the key moves to, or null when the key does not navigate. */
export function nextRowIndex(count: number, index: number, key: string): number | null {
  if (!count) return null;
  if (key === "ArrowDown") return Math.min(count - 1, index + 1);
  if (key === "ArrowUp") return Math.max(0, index - 1);
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

export function DataTable<Row>({
  label, columns, rows, rowKey, onOpen, selectedKey = null, rowMenu, loading = false, loadingLabel, onRetry, empty, testId = "data-table",
}: DataTableProps<Row>) {
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  if (loading) return createElement(LoadingState, { label: loadingLabel || label.toLowerCase(), variant: "table", onRetry });
  if (!rows.length) return createElement(EmptyLine, empty ?? { text: `No ${label.toLowerCase()} yet.` });

  const onRowKey = (event: KeyboardEvent<HTMLTableRowElement>, row: Row, index: number) => {
    if ((event.key === "Enter" || event.key === " ") && onOpen && event.target === event.currentTarget) {
      event.preventDefault();
      onOpen(row);
      return;
    }
    const next = nextRowIndex(rows.length, index, event.key);
    if (next === null) return;
    event.preventDefault();
    rowRefs.current[next]?.focus?.();
  };

  const headerCells: ReactElement[] = columns.map((column) =>
    createElement("th", {
      key: column.key, scope: "col",
      className: `ds-table__th${column.align === "end" ? " is-end" : ""}${column.grow ? " is-grow" : ""}`,
      style: column.width || column.minWidth ? { width: column.width, minWidth: column.minWidth } : undefined,
    }, column.header));
  if (rowMenu) headerCells.push(createElement("th", { key: "__menu", className: "ds-table__th ds-table__menu-cell" },
    createElement("span", { className: "ds-visually-hidden" }, "Actions")));

  const body = rows.map((row, index) => {
    const key = rowKey(row);
    const selected = selectedKey === key;
    const cells: ReactElement[] = columns.map((column) =>
      createElement("td", {
        key: column.key,
        className: `ds-table__td${column.nowrap ? " is-nowrap" : ""}${column.align === "end" ? " is-end" : ""}${column.grow ? " is-grow" : ""}`,
        style: column.minWidth ? { minWidth: column.minWidth } : undefined,
      }, column.clip
        ? createElement("span", { className: "ds-table__clip", style: { maxWidth: column.clip } }, column.render(row))
        : column.render(row)));
    if (rowMenu) cells.push(createElement("td", {
      key: "__menu", className: "ds-table__td ds-table__menu-cell",
      onClick: (event: { stopPropagation: () => void }) => event.stopPropagation(),
      onKeyDown: (event: { stopPropagation: () => void }) => event.stopPropagation(),
    }, rowMenu(row)));
    return createElement("tr", {
      key,
      ref: (node: HTMLTableRowElement | null) => { rowRefs.current[index] = node; },
      className: `ds-table__row${onOpen ? " is-interactive" : ""}${selected ? " is-selected" : ""}`,
      tabIndex: onOpen ? (selected || (!selectedKey && index === 0) ? 0 : -1) : undefined,
      "aria-selected": onOpen ? selected : undefined,
      "data-row-key": key,
      onClick: onOpen ? () => onOpen(row) : undefined,
      onKeyDown: (event: KeyboardEvent<HTMLTableRowElement>) => onRowKey(event, row, index),
    }, ...cells);
  });

  return createElement(
    "div",
    { className: "ds-table-wrap", "data-testid": testId },
    createElement(
      "table",
      { className: "ds-table", "aria-label": label },
      createElement("thead", null, createElement("tr", null, ...headerCells)),
      createElement("tbody", null, ...body),
    ),
  );
}
