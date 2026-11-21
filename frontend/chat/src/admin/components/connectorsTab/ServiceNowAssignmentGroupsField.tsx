import { useState } from "react";

import {
  FILTER_MODES,
  GROUPS_FIELD,
  GROUPS_HELP,
  MODE_FIELD,
  MODE_HELP,
  SERVICES_FIELD,
  SERVICES_HELP,
  addGroup,
  draftGroups,
  draftMode,
  groupsDraftValue,
  removeGroup,
  suggestionsFor,
} from "./serviceNowGroupsModel";
import type { KnownValue, LimitNoun } from "./serviceNowGroupsModel";
import { useKnownValues } from "./useServiceNowKnownValues";
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import "./serviceNowAssignmentGroups.css";

type AssignmentGroupsInputProps = {
  groups: string[];
  onChange: (groups: string[]) => void;
  id: string;
  label: string;
  help: string;
  emptyText: string;
  disabled?: boolean;
  testId: string;
  noun?: LimitNoun;
  // Known values (most frequent first), offered as the input's autocomplete; entries already listed are left out.
  suggestions?: readonly KnownValue[];
};

// ServiceNow assignment groups or services as chips with a remove button each, a text input and Add (Enter adds)
// (follow-ups C and 2). Used by the connector's limit and by the intake's narrowing overrides; each entry is
// checked with the backend's rules before it is added. Known values, when loaded, are the input's autocomplete.
export function AssignmentGroupsInput({ groups, onChange, id, label, help, emptyText, disabled = false, testId, noun = "group", suggestions = [] }: AssignmentGroupsInputProps) {
  const [entry, setEntry] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const offered = suggestionsFor(suggestions, groups);
  const add = () => {
    const result = addGroup(groups, entry, noun);
    setProblem(result.problem);
    if (result.problem) return;
    onChange(result.groups);
    setEntry("");
  };
  return (
    <div className="connector-field assignment-groups" data-testid={testId}>
      <label className="connector-field__label" htmlFor={id}>{label}</label>
      <span className="admin-panel__hint">{help}</span>
      <ul className="assignment-groups__chips" aria-label={label}>
        {groups.length ? groups.map((group, index) => (
          <li key={`${group}-${index}`} className="assignment-groups__chip" data-testid={`${testId}-chip`}>
            <span>{group}</span>
            {disabled ? null : (
              <button type="button" className="assignment-groups__remove" aria-label={`Remove ${group}`}
                onClick={() => { onChange(removeGroup(groups, index)); setProblem(null); }}>×</button>
            )}
          </li>
        )) : <li className="admin-panel__hint" data-testid={`${testId}-empty`}>{emptyText}</li>}
      </ul>
      {disabled ? null : (
        <div className="assignment-groups__add">
          <input id={id} type="text" className="connector-field__input" value={entry} placeholder={noun === "group" ? "Group name or sys_id" : "Service name or sys_id"}
            data-testid={`${testId}-input`} list={offered.length ? `${id}-known` : undefined}
            onChange={(event) => { setEntry(event.target.value); setProblem(null); }}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
          {offered.length ? (
            <datalist id={`${id}-known`} data-testid={`${testId}-known`}>
              {offered.map((value) => <option key={value.name} value={value.name}>{`${value.count} recent`}</option>)}
            </datalist>
          ) : null}
          <button type="button" className="admin-panel__action-btn" onClick={add} data-testid={`${testId}-add`}>Add</button>
        </div>
      )}
      {problem ? <span className="security-field-hint security-field-hint--error" role="alert" data-testid={`${testId}-problem`}>{problem}</span> : null}
    </div>
  );
}

/** The connector's record limit: groups and services (each a JSON array in the draft) and how they combine. */
export function ServiceNowAssignmentGroupsField({ connector, draft, set, id }: {
  connector: Pick<AdminConnector, "public_fields">;
  draft: Record<string, string>;
  set: (field: string, value: string) => void;
  id: (field: string) => string;
}) {
  const { known, state, load } = useKnownValues("/admin/chat/api/panel/connectors/servicenow/limit-values");
  const groups = draftGroups(connector, draft);
  const services = draftGroups(connector, draft, SERVICES_FIELD);
  const mode = draftMode(connector, draft);
  return (
    <>
      <AssignmentGroupsInput groups={groups} onChange={(next) => set(GROUPS_FIELD, groupsDraftValue(next))}
        id={id(GROUPS_FIELD)} label="Assignment groups" help={GROUPS_HELP} emptyText="No limit: records of every assignment group are read."
        testId="servicenow-assignment-groups" suggestions={known?.groups} />
      <AssignmentGroupsInput groups={services} onChange={(next) => set(SERVICES_FIELD, groupsDraftValue(next))} noun="service"
        id={id(SERVICES_FIELD)} label="Services" help={SERVICES_HELP} emptyText="No limit: records of every service are read."
        testId="servicenow-services" suggestions={known?.services} />
      {groups.length && services.length ? (
        <div className="connector-field assignment-groups" role="radiogroup" aria-label="Groups and services" data-testid="servicenow-filter-mode">
          <span className="connector-field__label">Groups and services</span>
          {FILTER_MODES.map((value) => (
            <label key={value} className="assignment-groups__mode">
              <input type="radio" name={id(MODE_FIELD)} value={value} checked={mode === value} onChange={() => set(MODE_FIELD, value)} />
              {MODE_HELP[value]}
            </label>
          ))}
        </div>
      ) : null}
      <div className="connector-field assignment-groups">
        <button type="button" className="admin-panel__action-btn" disabled={state === "loading"} onClick={() => void load()}
          data-testid="servicenow-known-values">
          {state === "loading" ? "Reading recent records…" : "Suggest groups and services from recent records"}
        </button>
        <span className="admin-panel__hint" role={state === "failed" ? "alert" : undefined}>
          {state === "failed" ? "Could not read recent records: save and test the connection first."
            : known ? `${known.groups.length} groups and ${known.services.length} services in the last ${known.scanned} records; type to pick one.`
              : "Reads the saved connection's latest incidents (read-only)."}
        </span>
      </div>
    </>
  );
}
