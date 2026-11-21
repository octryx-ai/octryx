import { Fragment } from "react";

import { levelColorClass } from "../settingsKit/SettingsKit";
import type { LevelRules, MatrixRow } from "./classificationMatrixRows";
import { cellDisplay, cellValue } from "./classificationMatrixRows";

export type MatrixLevel = { key: string; label: string; description: string; color: string | null; draft?: boolean };

// The levels × rules matrix: levels as columns, rules as rows grouped by family; a cell shows
// its value as a short phrase and opens the cell drawer. Cells that differ from the published policy are marked.
// A row added from the effect catalog: its cells come from the rule's threshold.
export type ExtraRow = { key: string; label: string; draft: boolean; cell: (level: string) => { text: string; tone: string }; onClick: () => void };

export function ClassificationMatrix({ levels, rows, rules, published, onCell, onLevel, extraRows = [] }: {
  levels: MatrixLevel[];
  rows: MatrixRow[];
  rules: LevelRules[];
  published: LevelRules[];
  onCell: (level: string, row: MatrixRow) => void;
  onLevel?: (level: string) => void;
  extraRows?: ExtraRow[];
}) {
  const rulesOf = (source: LevelRules[], level: string) => source.find((item) => item.level === level)?.rules;
  let family = "";
  return (
    <div className="sk-matrix-wrap">
      <table className="sk-matrix" data-testid="classification-matrix">
        <thead>
          <tr>
            <th scope="col">Rule</th>
            {levels.map((level) => (
              <th key={level.key} scope="col" className={level.draft ? "is-draft" : ""} title={level.description}>
                <button type="button" className="sk-cell-btn sk-lv" data-testid={`matrix-level-${level.key}`} disabled={!onLevel}
                  onClick={() => onLevel?.(level.key)}>
                  <span className={`sk-dot ${levelColorClass(level.color)}`} aria-hidden="true" />
                  {level.label}
                  {level.draft ? <span className="work-badge work-badge--attention">Draft</span> : null}
                </button>
                {level.description ? <small>{level.description}</small> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const header = row.family !== family ? (family = row.family) : null;
            return (
              <Fragment key={row.key}>
                {header ? <tr className="sk-fam"><th colSpan={levels.length + 1} scope="colgroup">{header}</th></tr> : null}
                <tr data-testid={`matrix-row-${row.key}`}>
                  <th scope="row">
                    {row.label}
                    {row.notEnforced ? <> <span className="work-badge work-badge--neutral">Not enforced yet</span></> : null}
                    {row.derived ? <> <span className="work-badge work-badge--neutral">From Model catalog</span></> : null}
                    {row.sub ? <small>{row.sub}</small> : null}
                  </th>
                  {levels.map((level) => {
                    const value = cellValue(row, rulesOf(rules, level.key));
                    const changed = JSON.stringify(value) !== JSON.stringify(cellValue(row, rulesOf(published, level.key)));
                    const shown = cellDisplay(row, value);
                    return (
                      <td key={level.key} className={changed || level.draft ? "is-draft" : ""}>
                        <button type="button" className={`sk-cell-btn sk-cell ${shown.tone ? `sk-cell--${shown.tone}` : ""}`}
                          data-testid={`matrix-cell-${row.key}-${level.key}`}
                          title={row.derived ? "Set per model in Runtime → Model catalog" : `Generated: classification:${level.key}:${row.policySuffix}`}
                          onClick={() => onCell(level.key, row)}>
                          {shown.text}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              </Fragment>
            );
          })}
          {extraRows.length ? <tr className="sk-fam"><th colSpan={levels.length + 1} scope="colgroup">Added rules</th></tr> : null}
          {extraRows.map((row) => (
            <tr key={row.key} data-testid={`matrix-row-${row.key}`}>
              <th scope="row">
                {row.label}
                {row.draft ? <> <span className="work-badge work-badge--attention">Draft</span></> : null}
              </th>
              {levels.map((level) => {
                const shown = row.cell(level.key);
                return (
                  <td key={level.key} className={row.draft ? "is-draft" : ""}>
                    <button type="button" className={`sk-cell-btn sk-cell ${shown.tone ? `sk-cell--${shown.tone}` : ""}`} onClick={row.onClick}>
                      {shown.text}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
