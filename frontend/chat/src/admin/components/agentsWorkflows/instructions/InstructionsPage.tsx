// Agents & workflows → Instructions: guidance the agent reads, bound explicitly: always in a
// scope, when a workflow is selected, or on request by key. No keyword or domain scoring. Every publish runs the
// conflict check and needs a second reviewer.
import { useCallback, useEffect, useState, type KeyboardEvent } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { Badge } from "../awBadges";
import "../agentsWorkflows.css";
import { EFFECTIVE_SETUP_PATH, readSetupOptions, type SetupOptions } from "../effectiveSetup/effectiveSetupModel";
import { InstructionDrawer } from "./InstructionDrawer";
import {
  INSTRUCTIONS_PATH,
  boundLabel,
  filterInstructions,
  readInstructions,
  scopeLabel,
  statusLabel,
  type InstructionRow,
  type InstructionScopeFilter,
} from "./instructionsModel";

const NO_OPTIONS: SetupOptions = { projects: [], users: [], agents: [], workflows: [] };

export function InstructionsPage({ readJson }: { readJson: ReadJsonFn }) {
  const [rows, setRows] = useState<InstructionRow[] | null>(null);
  const [options, setOptions] = useState<SetupOptions>(NO_OPTIONS);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<InstructionScopeFilter>("");
  const [open, setOpen] = useState<{ row: InstructionRow | null } | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(readInstructions(await readJson<unknown>(INSTRUCTIONS_PATH)));
      setProblem(null);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The instructions could not be loaded.");
    }
  }, [readJson]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    readJson<unknown>(`${EFFECTIVE_SETUP_PATH}/options`).then((raw) => setOptions(readSetupOptions(raw)), () => undefined);
  }, [readJson]);

  const onRowKey = (event: KeyboardEvent, row: InstructionRow) => {
    if (event.key === "Enter") setOpen({ row });
  };
  const visible = rows ? filterInstructions(rows, query, scope) : [];

  return (
    <div className="aw-page" data-testid="instructions-page">
      <p className="admin-panel__hint">
        Guidance the agent reads, bound <b>explicitly</b>: always in a scope, or when a workflow is selected. No keyword
        or domain scoring. Every publish runs the conflict check and needs a second reviewer.
      </p>
      <div className="aw-toolbar">
        <input className="admin-users__toolbar-input" value={query} aria-label="Search instructions"
          placeholder="Search instructions" onChange={(event) => setQuery(event.target.value)} />
        <select className="admin-users__toolbar-select" value={scope} aria-label="Scope"
          onChange={(event) => setScope(event.target.value as InstructionScopeFilter)}>
          <option value="">Any scope</option>
          <option value="global">Global</option>
          <option value="workspace">Workspace</option>
          <option value="workflow">Workflow</option>
          <option value="agent">Agent</option>
        </select>
        <span className="aw-toolbar__spacer" />
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setOpen({ row: null })}>
          + New instruction
        </button>
      </div>
      {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
      {!rows && !problem ? <p className="admin-panel__hint" role="status">Loading instructions…</p> : null}
      {rows && visible.length === 0 ? <div className="admin-panel__empty-state">No instruction matches.</div> : null}
      {visible.length ? (
        <table className="admin-panel__table aw-cards aw-table">
          <thead>
            <tr><th>Instruction</th><th>Scope</th><th>Bound to</th><th>Tokens</th><th>Conflicts</th><th>Version</th><th>Status</th></tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const status = statusLabel(row);
              const latest = row.latest ?? row.published;
              const conflicts = latest?.findings.length ?? 0;
              return (
                <tr key={row.id} tabIndex={0} onClick={() => setOpen({ row })} onKeyDown={(event) => onRowKey(event, row)}
                  data-testid={`instruction-row-${row.key}`}>
                  <td data-l="Instruction"><div className="aw-name">{row.title}</div><div className="aw-sub aw-mono">{row.key}</div></td>
                  <td data-l="Scope">{scopeLabel(row)}</td>
                  <td data-l="Bound to">{boundLabel(row)}</td>
                  <td data-l="Tokens">{latest?.tokenEstimate ?? 0}</td>
                  <td data-l="Conflicts">
                    {conflicts ? <Badge kind="danger">{`${conflicts} conflicts`}</Badge> : <Badge kind="active">none</Badge>}
                  </td>
                  <td data-l="Version">{latest ? `v${latest.version}` : "–"}</td>
                  <td data-l="Status"><Badge kind={status.kind}>{status.label}</Badge></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      <div className="aw-note">
        Order the agent reads: <b>System prompt texts → Agent instructions → Workspace instructions → Workflow instructions →
        Skills (on demand)</b>. Each layer has a budget; going over it is a conflict at publish, never a silent cut at run time.
      </div>
      {open ? (
        <InstructionDrawer row={open.row} options={options} readJson={readJson} onClose={() => setOpen(null)}
          onChanged={() => void load()} />
      ) : null}
    </div>
  );
}
