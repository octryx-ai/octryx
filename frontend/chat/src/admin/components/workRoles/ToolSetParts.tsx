// The parts of a function's tool set panel: its details, the catalog groups by risk, and patterns and other entries.
import type { Dispatch, SetStateAction } from "react";

import { FormSection } from "../../../layout/FormSection";
import { RISK_LABEL, toggleEntry, type ToolGroupView } from "./workRolesModel";
import { CheckRow } from "./WorkRolesParts";
import type { ToolCatalog, WorkFunction } from "./workRolesTypes";

type EntryProps = {
  has: (entry: string) => boolean;
  set: (entry: string, on: boolean) => void;
  readOnly: boolean;
};

export function ToolSetDetails({ fn, name, setName, description, setDescription, readOnly }: {
  fn: WorkFunction;
  name: string;
  setName: (name: string) => void;
  description: string;
  setDescription: (description: string) => void;
  readOnly: boolean;
}) {
  return (
    <FormSection title="Function">
      <label className="wr-field"><span>Name</span>
        <input value={name} disabled={readOnly} onChange={(event) => setName(event.target.value)} /></label>
      <div className="wr-field"><span>Key</span><span className="wr-field__key">{fn.key}</span></div>
      <label className="wr-field"><span>Description</span>
        <textarea value={description} rows={3} disabled={readOnly} onChange={(event) => setDescription(event.target.value)} /></label>
    </FormSection>
  );
}

export function ToolSetSelectors({ catalog, has, set, readOnly }: EntryProps & { catalog: ToolCatalog }) {
  return (
    <FormSection title="Whole groups">
      <div className="wr-checks">
        {catalog.selectors.map((selector) => (
          <CheckRow key={selector.entry} checked={has(selector.entry)} disabled={readOnly} title={selector.label}
            sub={<span className="wr-mono">{selector.entry}</span>} onChange={(on) => set(selector.entry, on)} />
        ))}
      </div>
    </FormSection>
  );
}

// One connector's tools by risk, each risk with Select all / Clear.
export function ToolGroupSection({ group, has, set, readOnly, setEntries }: EntryProps & {
  group: ToolGroupView;
  setEntries: Dispatch<SetStateAction<string[]>>;
}) {
  return (
    <section className="wr-tools-group" aria-label={group.label}>
      <h3 className="wr-tools-group__title">{group.label}</h3>
      {group.risks.map(({ risk, tools }) => {
        const picked = tools.filter((tool) => has(tool.name)).length;
        return (
          <div key={risk} className="wr-tools-risk">
            <div className="wr-tools-risk__head">
              <span className="wr-tools-risk__label">{RISK_LABEL[risk]} · {picked} of {tools.length}</span>
              {readOnly ? null : (
                <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost"
                  onClick={() => setEntries((current) => tools.reduce((acc, tool) => toggleEntry(acc, tool.name, picked < tools.length), current))}>
                  {picked < tools.length ? "Select all" : "Clear"}
                </button>
              )}
            </div>
            <div className="wr-checks">
              {tools.map((tool) => (
                <CheckRow key={tool.name} checked={has(tool.name)} disabled={readOnly} title={tool.name} sub={tool.description}
                  testId={`tool-${tool.name}`} onChange={(on) => set(tool.name, on)} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

// Entries that are not a catalog tool (patterns, selectors typed in) and the field to add one.
export function ToolSetPatterns({ extras, unknown, newEntry, setNewEntry, has, set, readOnly }: EntryProps & {
  extras: string[];
  unknown: string[];
  newEntry: string;
  setNewEntry: (entry: string) => void;
}) {
  return (
    <FormSection title="Patterns and other entries">
      {extras.length ? (
        <div className="wr-checks">
          {extras.map((entry) => (
            <CheckRow key={entry} checked disabled={readOnly} title={<span className="wr-mono">{entry}</span>}
              sub={unknown.includes(entry) ? "Matches no tool today." : undefined} onChange={() => set(entry, false)} />
          ))}
        </div>
      ) : <p className="wr-hint">No pattern. A pattern such as jira_* or connector:jira:write also covers tools added later.</p>}
      {readOnly ? null : (
        <div className="wr-add-entry wr-field">
          <input className="wr-mono" value={newEntry} placeholder="jira_* or connector:jira:write" aria-label="New entry"
            onChange={(event) => setNewEntry(event.target.value)} />
          <button type="button" className="ds-btn" disabled={!newEntry.trim() || has(newEntry.trim())}
            onClick={() => { set(newEntry.trim(), true); setNewEntry(""); }}>Add</button>
        </div>
      )}
    </FormSection>
  );
}
