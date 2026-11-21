import { useEffect, useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { listFunctions, loadToolCatalog, saveFunctionTools, updateFunction } from "./workRolesApi";
import {
  errorView,
  extraEntries,
  toggleEntry,
  toolGroups,
  unknownEntriesText,
  type ErrorView,
} from "./workRolesModel";
import { ErrorLine } from "./WorkRolesParts";
import { ToolGroupSection, ToolSetDetails, ToolSetPatterns, ToolSetSelectors } from "./ToolSetParts";
import type { ToolCatalog, WorkFunction } from "./workRolesTypes";

// The function as saved, the open tab, the catalog, the edited entries, name and description, and the busy/error
// state. All of it lives in the panel, so switching tabs keeps every unsaved edit.
function useToolSet(initial: WorkFunction) {
  const [fn, setFn] = useState(initial);
  const [tab, setTab] = useState<"tools" | "details">("tools");
  const [catalog, setCatalog] = useState<ToolCatalog | null>(null);
  const [entries, setEntries] = useState<string[]>(initial.tools);
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [newEntry, setNewEntry] = useState("");
  const [error, setError] = useState<ErrorView | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadToolCatalog(fn.id)
      .then((answer) => { if (!cancelled) setCatalog(answer); })
      .catch((failure) => { if (!cancelled) setError(errorView(failure, "The tool catalog could not be loaded.")); });
    return () => { cancelled = true; };
  }, [fn.id]);

  return {
    fn, setFn, tab, setTab, catalog, entries, setEntries, name, setName, description, setDescription, newEntry, setNewEntry,
    error, setError, busy, setBusy,
  };
}

type ToolSet = ReturnType<typeof useToolSet>;

// Saves through `action`, closes on success; a version conflict reloads the function and keeps the panel open.
function toolSetRunner(state: ToolSet, onSaved: () => void, onClose: () => void) {
  const { fn, setFn, setEntries, setName, setDescription, setError, setBusy } = state;
  const reload = async () => {
    const fresh = (await listFunctions(fn.workspace_id)).find((item) => item.id === fn.id);
    if (!fresh) return;
    setFn(fresh);
    setEntries(fresh.tools);
    setName(fresh.name);
    setDescription(fresh.description);
  };

  const run = async (action: () => Promise<WorkFunction>) => {
    setBusy(true);
    setError(null);
    try {
      const saved = await action();
      setFn(saved);
      setEntries(saved.tools);
      onSaved();
      onClose();
    } catch (failure) {
      const view = errorView(failure);
      setError(view);
      if (view.conflict) await reload().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };
  return run;
}

// Close (read-only), else Cancel and the save of the open tab.
function ToolSetFooter({ readOnly, tab, busy, canSaveTools, canSaveDetails, onClose, onSaveTools, onSaveDetails }: {
  readOnly: boolean;
  tab: "tools" | "details";
  busy: boolean;
  canSaveTools: boolean;
  canSaveDetails: boolean;
  onClose: () => void;
  onSaveTools: () => void;
  onSaveDetails: () => void;
}) {
  if (readOnly) return <button type="button" className="ds-btn" onClick={onClose}>Close</button>;
  return (
    <>
      <button type="button" className="ds-btn" onClick={onClose}>Cancel</button>
      {tab === "tools" ? (
        <button type="button" className="ds-btn ds-btn--primary" data-testid="tools-save" disabled={busy || !canSaveTools}
          onClick={onSaveTools}>{busy ? "Saving…" : "Save tools"}</button>
      ) : (
        <button type="button" className="ds-btn ds-btn--primary" disabled={busy || !canSaveDetails} onClick={onSaveDetails}>
          {busy ? "Saving…" : "Save"}
        </button>
      )}
    </>
  );
}

// A function's tool set (contract §2.4, §3.6): the catalog grouped by connector and risk, the offered selectors
// ("Every read tool"), entries that match no tool today, and the function's name and description. Saving sends
// expected_tools_version; a conflict reloads.
export function ToolSetPanel({ fn: initial, roleNames, canEdit, onClose, onSaved }: {
  fn: WorkFunction;
  roleNames: string[];
  canEdit: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const state = useToolSet(initial);
  const { fn, tab, setTab, catalog, entries, setEntries, name, setName, description, setDescription, newEntry, setNewEntry, error, busy } = state;
  const run = toolSetRunner(state, onSaved, onClose);

  const toolsChanged = JSON.stringify([...entries].sort()) !== JSON.stringify([...fn.tools].sort());
  const detailsChanged = name.trim() !== fn.name || description.trim() !== fn.description;
  const has = (entry: string) => entries.includes(entry);
  const set = (entry: string, on: boolean) => setEntries((current) => toggleEntry(current, entry, on));
  const extras = catalog ? extraEntries(entries, catalog) : [];
  const unknown = catalog ? catalog.unknown_entries.filter((entry) => entries.includes(entry)) : [];
  const unknownText = unknownEntriesText(unknown);
  const readOnly = !canEdit;

  const footer = (
    <ToolSetFooter readOnly={readOnly} tab={tab} busy={busy} canSaveTools={toolsChanged} canSaveDetails={detailsChanged && Boolean(name.trim())}
      onClose={onClose} onSaveTools={() => void run(() => saveFunctionTools(fn.id, entries, fn.tools_version))}
      onSaveDetails={() => void run(() => updateFunction(fn.id, { name: name.trim(), description: description.trim(), expected_version: fn.version }))} />
  );

  return (
    <SidePanel title={fn.name} subtitle={roleNames.length ? `In ${roleNames.join(", ")}` : "In no role yet"} onClose={onClose} footer={footer}
      testId="tool-set-panel"
      tabs={{ label: "Function", idPrefix: "fn-tabs", value: tab, onChange: (key) => setTab(key as "tools" | "details"),
        tabs: [{ key: "tools", label: "Tools", count: entries.length }, { key: "details", label: "Details" }] }}>
      <div className="wr-form">
        <ErrorLine error={error} />
        {tab === "details" ? (
          <ToolSetDetails fn={fn} name={name} setName={setName} description={description} setDescription={setDescription}
            readOnly={readOnly} />
        ) : !catalog ? (
          error ? null : <p className="wr-hint" role="status">Loading the tool catalog…</p>
        ) : (
          <>
            {unknownText ? <p className="wr-notice" data-testid="unknown-entries">{unknownText}</p> : null}
            {catalog.selectors.length ? <ToolSetSelectors catalog={catalog} has={has} set={set} readOnly={readOnly} /> : null}
            {toolGroups(catalog).map((group) => (
              <ToolGroupSection key={group.key} group={group} has={has} set={set} readOnly={readOnly} setEntries={setEntries} />
            ))}
            <ToolSetPatterns extras={extras} unknown={unknown} newEntry={newEntry} setNewEntry={setNewEntry} has={has} set={set}
              readOnly={readOnly} />
          </>
        )}
      </div>
    </SidePanel>
  );
}
