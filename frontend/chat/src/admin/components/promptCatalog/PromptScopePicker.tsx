import { ChoiceGroup } from "../../../layout/ChoiceGroup";
import { SCOPE_LABEL, scopeKey, type ScopeRef } from "./promptCatalogModel";
import type { PromptScopeType } from "./promptCatalogTypes";

export type ScopeChoice = ScopeRef & { label: string; writable: boolean };

type Props = {
  choices: ScopeChoice[];
  value: ScopeRef;
  onChange: (scope: ScopeRef) => void;
};

const TYPES: PromptScopeType[] = ["global", "workflow", "workspace"];

// Where a text applies: global, one workflow or one Workspace. The kind is a choice; a workflow or Workspace is
// picked by name when there is more than one. Kinds without any scope the user can see are disabled, so a
// Workspace owner never gets offered a global draft the server would refuse.
export function PromptScopePicker({ choices, value, onChange }: Props) {
  const ofType = (type: PromptScopeType) => choices.filter((choice) => choice.scope_type === type);
  const current = ofType(value.scope_type);
  return (
    <div className="pc-row" data-testid="pc-scope">
      <ChoiceGroup
        label="Scope"
        value={value.scope_type}
        choices={TYPES.map((type) => ({ key: type, label: SCOPE_LABEL[type], disabled: !ofType(type).length }))}
        onChange={(key) => {
          const first = ofType(key as PromptScopeType)[0];
          if (first) onChange(first);
        }}
      />
      {value.scope_type !== "global" && current.length ? (
        <select
          className="admin-users__toolbar-select pc-scope-select"
          aria-label={`${SCOPE_LABEL[value.scope_type]} of this text`}
          value={scopeKey(value)}
          onChange={(event) => {
            const next = current.find((choice) => scopeKey(choice) === event.target.value);
            if (next) onChange(next);
          }}
        >
          {current.map((choice) => (
            <option key={scopeKey(choice)} value={scopeKey(choice)}>
              {choice.label}
              {choice.writable ? "" : " (read only)"}
            </option>
          ))}
        </select>
      ) : null}
    </div>
  );
}
