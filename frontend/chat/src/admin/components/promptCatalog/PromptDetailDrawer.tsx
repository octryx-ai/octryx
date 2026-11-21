import { GovernedDrawer } from "../governedRegistry/GovernedDrawer";
import { PromptRefusalBox } from "./PromptRefusalBox";
import { RiskBadge } from "./PromptCatalogList";
import { PromptDiffView } from "./PromptDiffView";
import { PromptPlaceholderList } from "./PromptPlaceholderList";
import { PromptEffectiveSection, PromptVersionsTable, VersionPanel } from "./PromptDetailParts";
import { usePromptDetailScope } from "./usePromptDetailScope";
import { contextOf, effectiveText, isOverridden, publishedVersion, scopeKey, scopeLabel, type ScopeRef } from "./promptCatalogModel";
import type { PromptDetail } from "./promptCatalogTypes";
import type { PromptDetailModel } from "./usePromptCatalog";

type Props = {
  model: PromptDetailModel;
  // The scope the page was opened for (workflow editor link "Texts of this workflow"); null: global.
  initialScope: ScopeRef | null;
  currentUserId?: string;
  onNewDraft: (base: { scope: ScopeRef; scopeLabel: string; body: string }) => void;
  onClose: () => void;
};

// The title, the description and the placeholders (or that the text is served verbatim).
function PromptContract({ detail }: { detail: PromptDetail }) {
  return (
    <>
      <div className="ws-section">
        <div className="pc-row">
          <strong>{detail.title}</strong>
          <RiskBadge risk={detail.risk} />
        </div>
        {detail.description ? <span className="ws-muted">{detail.description}</span> : null}
      </div>
      <div className="ws-section">
        <div className="admin-panel__section-header">
          <span>Placeholders</span>
        </div>
        {detail.literal ? (
          <span className="ws-muted">Served verbatim: braces are plain text, not placeholders.</span>
        ) : (
          <PromptPlaceholderList placeholders={detail.placeholders} descriptions={detail.placeholder_descriptions} />
        )}
      </div>
    </>
  );
}

// One System prompt text: its contract (placeholders), the shipped text, every version (global; retired
// Workspace / agent rows stay listed for the audit trail), the lifecycle of the selected version and
// "Revert to shipped" when the published text is an override.
export function PromptDetailDrawer({ model, initialScope, currentUserId, onNewDraft, onClose }: Props) {
  const { detail } = model;
  const { selectedId, setSelectedId, scope, setScope, choices, projectNames } = usePromptDetailScope(detail, initialScope);
  const chosen = choices.find((choice) => scopeKey(choice) === scopeKey(scope));
  const effective = detail ? effectiveText(detail.templates, detail.seed, contextOf(scope)) : null;
  const versions = detail?.templates.flatMap((template) => template.versions.map((version) => ({ template, version }))) ?? [];
  const selected = versions.find((item) => item.version.id === selectedId);
  const globalTemplate = detail?.templates.find((template) => template.scope_type === "global");
  const globalPublished = publishedVersion(globalTemplate);
  const overridden = detail
    ? isOverridden({ published: globalPublished ?? null, seed_digest: detail.seed_digest })
    : false;

  return (
    <GovernedDrawer variant="detail" eyebrow="Prompt" title={detail?.key ?? "Loading…"} onClose={onClose}>
      {!detail && model.busy === "load" ? <div className="admin-panel__empty-state">Loading prompt…</div> : null}
      {model.notice ? <div className="ws-alert ws-alert--success">{model.notice}</div> : null}
      <PromptRefusalBox refusal={model.refusal} />
      {detail ? (
        <>
          <PromptContract detail={detail} />
          <PromptEffectiveSection detail={detail} model={model} choices={choices} scope={scope} setScope={setScope} chosen={chosen}
            effective={effective} projectNames={projectNames} overridden={overridden} onNewDraft={onNewDraft} />
          {model.diff ? <PromptDiffView diff={model.diff} onClose={model.clearDiff} /> : null}
          {selected ? (
            <VersionPanel
              model={model}
              template={selected.template}
              version={selected.version}
              label={scopeLabel(selected.template, projectNames)}
              currentUserId={currentUserId}
              writable={choices.some((choice) => choice.writable && scopeKey(choice) === scopeKey(selected.template))}
              onDraftFrom={() =>
                onNewDraft({
                  scope: { scope_type: selected.template.scope_type, scope_id: selected.template.scope_id },
                  scopeLabel: projectNames.get(scopeKey(selected.template)) ?? scopeLabel(selected.template, projectNames),
                  body: selected.version.body ?? "",
                })
              }
            />
          ) : null}
          <PromptVersionsTable versions={versions} projectNames={projectNames} selectedId={selectedId}
            onView={(versionId) => { model.clearMessages(); setSelectedId(versionId); }} />
          <div className="ws-section">
            <div className="admin-panel__section-header">
              <span>Shipped text</span>
              <code className="ws-mono">{detail.seed_digest.slice(0, 19)}…</code>
            </div>
            <span className="ws-muted">Served when no reviewed override is published.</span>
            <pre className="pc-body">{detail.seed}</pre>
          </div>
        </>
      ) : null}
    </GovernedDrawer>
  );
}
