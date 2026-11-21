import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { AtlassianAuthFields } from "./AtlassianAuthFields";
import { FieldError } from "./ConnectorCredentialInput";
import {
  JIRA_DRAFT_CONFIRM_ALL,
  JIRA_DRAFT_SCOPE,
  JIRA_PROJECTS_FIELD,
  projectsDisplayText,
} from "./jiraConnectorSetupModel";
import type { JiraFieldError, JiraSetupView } from "./jiraConnectorSetupModel";
import { ConnectorFieldGroup } from "./ConnectorFieldGroup";
import { GROUP_TITLES } from "./connectorFieldGroupsModel";
import "./jiraConnectorSetup.css";

type JiraConnectorSetupFieldsProps = {
  connector: any;
  draft: Record<string, string>;
  view: JiraSetupView;
  ctx: Record<string, unknown>;
  rebind: ConnectorSecretRebind;
  // After a save attempt every error shows; before, only errors about entered content.
  showAllErrors: boolean;
};

// The guided Jira form: the shared Atlassian sign-in and an explicit project scope.
export function JiraConnectorSetupFields({ connector, draft, view, ctx, rebind, showAllErrors }: JiraConnectorSetupFieldsProps) {
  const { setConnectorField: setDraftField } = ctx as Record<string, any>;
  const toolName: string = connector.tool_name;
  const set = (field: string, value: string) => {
    setDraftField(toolName, field, value);
    rebind.fieldEdited(field);
  };
  const id = (field: string) => connectorFieldInputId(toolName, field);
  const shown = (field: string): JiraFieldError | null => {
    const error = view.errors[field];
    return error && (error.live || showAllErrors) ? error : null;
  };
  const projectsText = projectsDisplayText(draft[JIRA_PROJECTS_FIELD]);

  return (
    <>
      {(["connection", "authentication"] as const).map((part) => (
        <ConnectorFieldGroup key={part} group={part} title={GROUP_TITLES[part]}>
          <div className="connector-card__fields">
            <AtlassianAuthFields product="jira" connector={connector} draft={draft} view={view.auth} set={set}
              rebind={rebind} showAllErrors={showAllErrors} part={part} />
          </div>
        </ConnectorFieldGroup>
      ))}
      <ConnectorFieldGroup group="scope" title={GROUP_TITLES.scope}>
      <div className="connector-field jira-setup__group" role="radiogroup" aria-labelledby={`${id(JIRA_DRAFT_SCOPE)}-label`}>
        <span id={`${id(JIRA_DRAFT_SCOPE)}-label`} className="connector-field__label">Project access</span>
        <span className="admin-panel__hint">
          {view.storedProjects
            ? `Currently saved: only ${view.storedProjects.join(", ")}.`
            : connector.configured
              ? "Currently saved: no project restriction (all projects this account can access)."
              : "Nothing saved yet."}
        </span>
        <div className="jira-setup__options">
          <label className="jira-setup__option">
            <input type="radio" name={id(JIRA_DRAFT_SCOPE)} value="restricted" checked={view.scope === "restricted"}
              onChange={() => set(JIRA_DRAFT_SCOPE, "restricted")} />
            <span className="jira-setup__option-text">
              <strong>Only these projects</strong><span className="ds-sr-only"> · agents can reach only the listed Jira projects.</span>
            </span>
          </label>
          <label className="jira-setup__option">
            <input type="radio" name={id(JIRA_DRAFT_SCOPE)} value="all" checked={view.scope === "all"}
              onChange={() => set(JIRA_DRAFT_SCOPE, "all")} />
            <span className="jira-setup__option-text">
              <strong>All projects this account can access</strong><span className="ds-sr-only"> · no project restriction.</span>
            </span>
          </label>
        </div>
        {view.scope === "restricted" ? (
          <>
            <label className="connector-field__label" htmlFor={id(JIRA_PROJECTS_FIELD)}>Project keys</label>
            <textarea
              id={id(JIRA_PROJECTS_FIELD)}
              className={`connector-field__input connector-field__input--textarea${errorClass(shown(JIRA_PROJECTS_FIELD))}`}
              value={projectsText}
              onChange={(event) => set(JIRA_PROJECTS_FIELD, event.target.value)}
              placeholder={"One project key per line\nPROJ1\nPROJ2"}
              rows={4}
              spellCheck={false}
              aria-invalid={Boolean(shown(JIRA_PROJECTS_FIELD))}
            />
            {/* A preview of the unsaved draft, shown only while every entry is a valid key. */}
            {view.projects.keys.length && !view.projects.invalid.length ? (
              <span className="admin-panel__hint">Will save as: {view.projects.keys.join(", ")}</span>
            ) : null}
            <FieldError error={shown(JIRA_PROJECTS_FIELD)} />
          </>
        ) : view.broadening ? (
          <>
            <span className="security-field-hint security-field-hint--attention">
              Saving removes the restriction to {view.storedProjects?.join(", ")}: agents can then reach every project this
              account can access.
            </span>
            <label className="jira-setup__option">
              <input
                type="checkbox"
                checked={draft[JIRA_DRAFT_CONFIRM_ALL] === "true"}
                onChange={(event) => set(JIRA_DRAFT_CONFIRM_ALL, event.target.checked ? "true" : "false")}
              />
              <span className="jira-setup__option-text">I confirm removing the project restriction.</span>
            </label>
            <FieldError error={shown(JIRA_DRAFT_CONFIRM_ALL)} />
          </>
        ) : null}
      </div>
      </ConnectorFieldGroup>
    </>
  );
}

function errorClass(error: JiraFieldError | null): string {
  return error ? " security-field--error" : "";
}
