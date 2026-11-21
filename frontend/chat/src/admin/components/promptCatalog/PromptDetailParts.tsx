import { RevisionStateBadge } from "../governedRegistry/GovernedDrawer";
import { PromptVersionActions } from "./PromptVersionActions";
import { PromptScopePicker } from "./PromptScopePicker";
import { SCOPE_LABEL, effectiveText, scopeChoices, scopeKey, scopeLabel, sourceLabel, type ScopeRef } from "./promptCatalogModel";
import type { PromptDetail, PromptTemplateView, PromptVersion } from "./promptCatalogTypes";
import type { PromptDetailModel } from "./usePromptCatalog";
import { formatDateTime } from "../../utils/dateTime";

type Choice = ReturnType<typeof scopeChoices>[number];
type Effective = ReturnType<typeof effectiveText> | null;

function formatDate(value: string | null | undefined): string {
  return value ? formatDateTime(value) : "—";
}

type EffectiveProps = {
  detail: PromptDetail;
  model: PromptDetailModel;
  choices: Choice[];
  scope: ScopeRef;
  setScope: (scope: ScopeRef) => void;
  chosen: Choice | undefined;
  effective: Effective;
  projectNames: Map<string, string>;
  overridden: boolean;
  onNewDraft: (base: { scope: ScopeRef; scopeLabel: string; body: string }) => void;
};

// "Text in use": the scope picker, the text a run there gets and where it comes from, and the draft actions.
export function PromptEffectiveSection({ detail, model, choices, scope, setScope, chosen, effective, projectNames, overridden, onNewDraft }: EffectiveProps) {
  return (
    <div className="ws-section" data-testid="pc-effective">
      <div className="admin-panel__section-header">
        <span>Text in use</span>
      </div>
      <PromptScopePicker choices={choices} value={scope} onChange={setScope} />
      {effective ? (
        <span className="pc-source" data-testid="pc-effective-source">
          {scopeIntro(scope, projectNames)} uses {sourceLabel(effective.scope, projectNames)}
          {effective.version ? ` (v${effective.version.version})` : ""}.
        </span>
      ) : null}
      <pre className="pc-body">{effective?.body}</pre>
      {chosen && !chosen.writable ? (
        <span className="ws-muted">{readOnlyText(scope)}</span>
      ) : null}
      <div className="pc-row">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={!chosen?.writable}
          onClick={() =>
            onNewDraft({ scope, scopeLabel: chosen?.label ?? "Global", body: effective?.body ?? detail.seed })
          }
        >
          New draft for {scope.scope_type === "global" ? "global" : chosen?.label ?? scope.scope_id}…
        </button>
        {overridden && scope.scope_type === "global" && chosen?.writable ? (
          <button type="button" className="admin-panel__action-btn" disabled={model.busy !== null}
            onClick={() => void model.revert(detail.key)}>
            Revert to shipped
          </button>
        ) : null}
      </div>
    </div>
  );
}

// "Versions by scope": every version with its state and source; View selects it.
export function PromptVersionsTable({ versions, projectNames, selectedId, onView }: {
  versions: { template: PromptTemplateView; version: PromptVersion }[];
  projectNames: Map<string, string>;
  selectedId: string | null;
  onView: (versionId: string) => void;
}) {
  return (
    <div className="ws-section">
      <div className="admin-panel__section-header">
        <span>Versions by scope</span>
      </div>
      <table className="admin-panel__table" data-testid="pc-versions">
        <thead>
          <tr>
            <th>Scope</th>
            <th>Version</th>
            <th>State</th>
            <th>Source</th>
            <th>Published</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {versions.map(({ template, version }) => (
            <tr key={version.id}>
              <td>{scopeLabel(template, projectNames)}</td>
              <td>v{version.version}</td>
              <td>
                <RevisionStateBadge state={version.state} />
              </td>
              <td className="ws-nowrap">{version.source}</td>
              <td className="admin-panel__cell--muted">{formatDate(version.published_at)}</td>
              <td>
                <button
                  type="button"
                  className="admin-panel__action-btn"
                  disabled={selectedId === version.id}
                  onClick={() => onView(version.id)}
                >
                  View
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type VersionPanelProps = {
  model: PromptDetailModel;
  template: PromptTemplateView;
  version: PromptVersion;
  label: string;
  writable: boolean;
  currentUserId?: string;
  onDraftFrom: () => void;
};

export function VersionPanel({ model, template, version, label, writable, currentUserId, onDraftFrom }: VersionPanelProps) {
  return (
    <div className="ws-section" data-testid="pc-version">
      <div className="admin-panel__section-header">
        <span>
          {label} · v{version.version} · {version.source}
        </span>
        <RevisionStateBadge state={version.state} />
      </div>
      <span className="ws-muted">
        Digest <code className="ws-mono">{version.digest}</code>
        {version.change_note ? ` · ${version.change_note}` : ""}
      </span>
      <pre className="pc-body">{version.body}</pre>
      <PromptVersionActions key={version.id} model={model} version={version} currentUserId={currentUserId} />
      {writable ? (
        <div className="pc-row">
          <button type="button" className="admin-panel__action-btn" onClick={onDraftFrom}>
            New draft from v{version.version} ({SCOPE_LABEL[template.scope_type].toLowerCase()})
          </button>
        </div>
      ) : null}
    </div>
  );
}

function scopeIntro(scope: ScopeRef, names: Map<string, string>): string {
  if (scope.scope_type === "global") return "A run without its own workflow or Workspace text";
  return `A run in ${SCOPE_LABEL[scope.scope_type].toLowerCase()} ${names.get(scopeKey(scope)) ?? scope.scope_id}`;
}

function readOnlyText(scope: ScopeRef): string {
  if (scope.scope_type === "global") return "Only a platform admin changes the global text; pick your workflow or Workspace.";
  if (scope.scope_type === "workflow") return "Only the workflow's creator or a platform admin changes its texts.";
  return "Only an owner or admin of this Workspace changes its texts.";
}
