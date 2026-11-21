// Stricter Workspace overrides of classification matrix rows.
import type { Rules } from "./classificationPolicyModel";
import { cellDisplay, cellOptions, type MatrixRow } from "./classificationMatrixRows";
import { isRecord, text } from "./classificationValueReaders";

// ---- stricter Workspace overrides ---------------------------------------------------------------

/** The rows a Workspace may override, and which of their values are stricter than (or equal to) the level's. */
export function overrideOptions(row: MatrixRow, levelValue: unknown): { value: unknown; text: string; allowed: boolean; level: boolean }[] {
  const order = row.options.map((option) => option.value);
  const strictness = (value: unknown) => {
    if (row.rule === "transcript_retention_days") return value === null ? -1 : 100_000 - Number(value);
    return order.indexOf(value);
  };
  const levelRank = strictness(levelValue);
  return cellOptions(row, levelValue).map((option) => ({
    value: option.value, text: option.text, allowed: strictness(option.value) >= levelRank, level: option.value === levelValue,
  }));
}

export const OVERRIDABLE_ROWS = new Set(["gateway", "seat", "device", "reranker", "embeddings", "logs", "retention"]);

export function overrideRows(rows: MatrixRow[]): MatrixRow[] {
  return rows.filter((row) => OVERRIDABLE_ROWS.has(row.key) || row.connector);
}

/** One row's value inside an overrides record. */
export function overrideValue(row: MatrixRow, overrides: Rules): unknown {
  if (row.connector) return isRecord(overrides.connectors) ? overrides.connectors[row.connector] : undefined;
  return overrides[row.rule];
}

export function setOverride(overrides: Rules, row: MatrixRow, value: unknown, levelValue: unknown): Rules {
  const next: Rules = { ...overrides };
  if (row.connector) {
    const connectors = { ...(isRecord(next.connectors) ? next.connectors : {}) };
    if (value === levelValue) delete connectors[row.connector];
    else connectors[row.connector] = value;
    if (Object.keys(connectors).length) next.connectors = connectors;
    else delete next.connectors;
    return next;
  }
  if (value === levelValue) delete next[row.rule];
  else next[row.rule] = value;
  return next;
}

export function overrideChips(rows: MatrixRow[], overrides: Rules): string[] {
  return overrideRows(rows).flatMap((row) => {
    const value = overrideValue(row, overrides);
    return value === undefined ? [] : [`${row.label}: ${cellDisplay(row, value).text.toLowerCase()}`];
  });
}
