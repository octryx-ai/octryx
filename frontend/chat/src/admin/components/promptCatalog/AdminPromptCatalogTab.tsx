import { useMemo, useState } from "react";
import { AreaPurpose } from "../workflowSurfaces/AreaPurpose";
import { PromptRefusalBox } from "./PromptRefusalBox";
import { PromptCatalogList } from "./PromptCatalogList";
import { PromptDetailDrawer } from "./PromptDetailDrawer";
import { PromptDraftEditor } from "./PromptDraftEditor";
import { readPromptScopeFromSearch } from "../../editorLinks";
import { SCOPE_LABEL, isOverridden, parseScopeKey, type ScopeRef } from "./promptCatalogModel";
import { usePromptCatalogList, usePromptDetail } from "./usePromptCatalog";
import "../governedRegistry/governedRegistry.css";
import "./promptCatalog.css";

// Settings → Platform → System prompt texts: every agent-facing text the platform ships. An override is a
// draft with a diff against the text it replaces and needs a second reviewer; each turn records which version it
// used. Run texts can also be written per workflow or Workspace; `?prompt_scope=workflow:<key>` (the
// workflow editor's "Texts of this workflow") shows the run texts with that scope chosen.
// One drawer at a time: the key's detail, or the editor for a new draft version.
export function AdminPromptCatalogTab({ currentUserId = "" }: { currentUserId?: string }) {
  const list = usePromptCatalogList();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [overriddenOnly, setOverriddenOnly] = useState(false);
  const [scope, setScope] = useState<ScopeRef | null>(() =>
    parseScopeKey(readPromptScopeFromSearch(typeof window === "undefined" ? "" : window.location.search)),
  );
  const items = useMemo(() => {
    let rows = list.items;
    // A workflow or Workspace has its own texts only for what a run sends its agent.
    if (rows && scope) rows = rows.filter((item) => item.area === RUN_AREA);
    if (rows && overriddenOnly) rows = rows.filter((item) => isOverridden(item));
    return rows;
  }, [list.items, overriddenOnly, scope]);

  return (
    <div className="ws-designer">
      <AreaPurpose
        links={[{ tab: "agents", label: "Agents" }]}
      />
      <div className="pc-row">
        {/* A choice in the toolbar, not a third tab row under Platform › Advanced (two levels). */}
        <select className="admin-users__toolbar-select" aria-label="System prompt text area" value={list.area ?? ""}
          onChange={(event) => list.setArea(event.target.value || null)} data-testid="prompt-area">
          <option value="">Prompts</option>
          {list.collapsed.map((entry) => (
            <option key={entry.area} value={entry.area}>
              {entry.area === "tool" ? "Tool descriptions" : "MCP descriptions"} ({entry.count})
            </option>
          ))}
        </select>
        <input
          className="admin-users__toolbar-input pc-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search key or text"
          aria-label="Search System prompt texts"
        />
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={overriddenOnly} onChange={(event) => setOverriddenOnly(event.target.checked)} />
          Overridden only
        </label>
      </div>
      {scope ? (
        <div className="pc-scope-banner" data-testid="pc-scope-banner">
          <span>
            Run texts of {SCOPE_LABEL[scope.scope_type].toLowerCase()} <code className="ws-mono">{scope.scope_id}</code>:
            open a text to see what this {SCOPE_LABEL[scope.scope_type].toLowerCase()}'s runs use and to change it.
          </span>
          <button type="button" className="admin-panel__action-btn" onClick={() => setScope(null)}>
            Show all texts
          </button>
        </div>
      ) : null}
      <PromptRefusalBox refusal={list.refusal} />
      {items === null && !list.refusal ? <div className="admin-panel__empty-state">Loading System prompt texts…</div> : null}
      {items ? <PromptCatalogList items={items} query={query} onOpen={setOpenKey} /> : null}
      {openKey ? (
        <PromptDrawers key={openKey} promptKey={openKey} initialScope={scope} currentUserId={currentUserId} onChanged={() => void list.reload()}
          onClose={() => setOpenKey(null)} />
      ) : null}
    </div>
  );
}

const RUN_AREA = "run";

type DrawersProps = {
  promptKey: string;
  initialScope: ScopeRef | null;
  currentUserId: string;
  onChanged: () => void;
  onClose: () => void;
};
type Editing = { scope: ScopeRef; scopeLabel: string; body: string };

function PromptDrawers({ promptKey, initialScope, currentUserId, onChanged, onClose }: DrawersProps) {
  const model = usePromptDetail(promptKey, onChanged);
  const [editing, setEditing] = useState<Editing | null>(null);

  if (editing && model.detail) {
    return (
      <PromptDraftEditor
        promptKey={promptKey}
        placeholders={model.detail.placeholders}
        placeholderDescriptions={model.detail.placeholder_descriptions}
        literal={Boolean(model.detail.literal)}
        scope={editing.scope}
        scopeLabel={editing.scopeLabel}
        initialBody={editing.body}
        onSaved={(version) => {
          setEditing(null);
          onChanged();
          void model.reload().then(() => model.showDiff(version.id));
        }}
        onClose={() => setEditing(null)}
      />
    );
  }
  return (
    <PromptDetailDrawer
      model={model}
      initialScope={initialScope}
      currentUserId={currentUserId}
      onNewDraft={(base) => {
        model.clearMessages();
        setEditing(base);
      }}
      onClose={onClose}
    />
  );
}
