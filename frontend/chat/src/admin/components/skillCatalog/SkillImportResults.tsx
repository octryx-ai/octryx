import { CategorySelect } from "./SkillImportUpload";
import { shortCommit } from "./skillCatalogModel";
import type { CategoryCatalog } from "./skillCatalogTypes";
import type { InspectItem, InspectResult, SourceRow } from "./skillDeliveryTypes";
import { canFollow, inspectedItems, itemKey, itemOffer, securityPreview, selectedItems } from "./skillImportModel";
import type { TrackingMode, Trust } from "./skillImportModel";

const ICONS = { ok: "✓", wa: "!", er: "✕", in: "i" } as const;

// The inspect result of a Git or marketplace import (mock `renderImport` step 1): what was found at the
// commit, which items can become drafts (an item already in the catalog is offered as its update, a taken name is
// refused), ignored components, MCP servers with their launch spec, and the import options.
export function SkillImportResults({ result, source, selected, categoryId, tags, tracking, trust, categories, onToggle, onCategory, onTags, onTracking, onTrust }: {
  result: InspectResult;
  /** The catalog source this repository already is, if any (its trust label stays unless changed in Sources). */
  source: SourceRow | null;
  selected: string[];
  categoryId: string;
  tags: string;
  tracking: TrackingMode;
  trust: Trust | "";
  categories: CategoryCatalog;
  onToggle: (key: string) => void;
  onCategory: (categoryId: string) => void;
  onTags: (tags: string) => void;
  onTracking: (mode: TrackingMode) => void;
  onTrust: (trust: Trust) => void;
}) {
  const items = inspectedItems(result);
  const chosen = selectedItems(result, selected);
  const preview = securityPreview(chosen);

  return (
    <div className="skills__import" data-testid="skill-import-results">
      <ImportSummary result={result} />

      <div className="admin-panel__card" style={{ padding: ".5rem .7rem" }} data-testid="skill-import-items">
        {items.length ? items.map((item) => (
          <ImportItemRow key={itemKey(item)} item={item} checked={selected.includes(itemKey(item))} onToggle={() => onToggle(itemKey(item))} />
        )) : <p className="skills__hint">Nothing to import: no folder with a SKILL.md and no MCP server in a plugin.</p>}
        {result.ignored.length ? (
          <div className="skills__import-item" data-testid="skill-import-ignored">
            <span className="skills__hint">Ignored (never imported):</span>
            {result.ignored.map((entry) => (
              <span key={entry.path} className="skills__hint"><span className="skills__mono">{entry.path}</span> · {entry.reason}</span>
            ))}
          </div>
        ) : null}
      </div>

      <ImportOptions result={result} source={source} categoryId={categoryId} tags={tags} tracking={tracking} trust={trust}
        categories={categories} onCategory={onCategory} onTags={onTags} onTracking={onTracking} onTrust={onTrust} />

      {chosen.length ? (
        <div className="admin-panel__card" data-testid="skill-import-security">
          <div className="admin-panel__section-header">Security review (preview)</div>
          {preview.map((line) => (
            <div key={line.id} className="skills__check">
              <span className={`skills__check-i skills__${line.tone}`} aria-hidden="true">{ICONS[line.tone]}</span><span>{line.text}</span>
            </div>
          ))}
        </div>
      ) : null}
      <p className="skills__hint">Imported entries start as drafts with provenance (repository, path, commit, licence). They are
        published after approval (Settings → Governance → Approval rule).</p>
    </div>
  );
}

// What was found at the commit: the plugin, the commit and ref, the licence and the counts.
function ImportSummary({ result }: { result: InspectResult }) {
  const plugin = result.plugin;
  const pluginText = (key: string) => (plugin && typeof plugin[key] === "string" ? (plugin[key] as string) : "");
  return (
    <div className="policies__note">
      {plugin ? (
        <>Plugin <b>{plugin.name}</b>{pluginText("author") ? `, author ${pluginText("author")}` : ""}
          {pluginText("description") ? ` · ${pluginText("description")}` : ""} · source <span className="skills__mono">{result.path || "/"}</span> · </>
      ) : null}
      Commit <span className="skills__mono">{shortCommit(result.commit)}</span>
      {result.ref && result.ref !== result.commit ? <> on <span className="skills__mono">{result.ref}</span></> : null}
      {result.licence?.spdx ? <> · licence <b>{result.licence.spdx}</b> ({result.licence.source})</> : " · no licence detected"}
      {" · "}{result.skills.length} skill{result.skills.length === 1 ? "" : "s"}, {result.mcp_servers.length} MCP server{result.mcp_servers.length === 1 ? "" : "s"} found.
    </div>
  );
}

// The import options: category for new entries, tracking (pinned or following the branch), tags and the source's trust.
function ImportOptions({ result, source, categoryId, tags, tracking, trust, categories, onCategory, onTags, onTracking, onTrust }: {
  result: InspectResult;
  source: SourceRow | null;
  categoryId: string;
  tags: string;
  tracking: TrackingMode;
  trust: Trust | "";
  categories: CategoryCatalog;
  onCategory: (categoryId: string) => void;
  onTags: (tags: string) => void;
  onTracking: (mode: TrackingMode) => void;
  onTrust: (trust: Trust) => void;
}) {
  const follow = canFollow(result.ref);
  return (
    <div className="admin-panel__form-grid">
      <CategorySelect value={categoryId} categories={categories} onChange={onCategory} label="Category for new entries" />
      <label className="admin-panel__field">
        <span>Tracking</span>
        <select value={tracking} data-testid="skill-import-tracking" onChange={(event) => onTracking(event.target.value as TrackingMode)}>
          <option value="pinned">Pinned to this commit ({shortCommit(result.commit)})</option>
          <option value="follow" disabled={!follow}>Follow the branch{follow ? ` (${result.ref})` : " (needs a branch or tag)"}</option>
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Tags</span>
        <input value={tags} placeholder="Comma-separated" data-testid="skill-import-git-tags" onChange={(event) => onTags(event.target.value)} />
      </label>
      {source ? (
        <div className="admin-panel__field">
          <span>Source</span>
          <span className="skills__hint">Already a catalog source: <b>{source.label}</b> ({source.trust}). Change its trust in Sources &amp; updates.</span>
        </div>
      ) : (
        <label className="admin-panel__field">
          <span>Trust of the new source</span>
          <select value={trust || "community"} data-testid="skill-import-trust" onChange={(event) => onTrust(event.target.value as Trust)}>
            <option value="official">Official (the publisher&apos;s own repository)</option>
            <option value="community">Community</option>
            <option value="internal">Internal</option>
          </select>
        </label>
      )}
    </div>
  );
}

function ImportItemRow({ item, checked, onToggle }: { item: InspectItem; checked: boolean; onToggle: () => void }) {
  const offer = itemOffer(item);
  const spec = item.launch_spec;
  const files = Array.isArray(item.files) ? item.files.length : item.files;
  return (
    <div className="skills__import-item" data-testid={`skill-import-item-${item.name}`}>
      <label className="skills__cbx">
        <input type="checkbox" checked={offer.importable && checked} disabled={!offer.importable} onChange={onToggle} />
        <span className="skills__mono">{item.name}</span>
        {item.kind === "mcp_server" ? <span className="skills__kind">MCP server</span> : null}
        {item.existing?.relation === "update" ? <span className="work-badge work-badge--running">In the catalog</span> : null}
      </label>
      <div className="skills__import-meta">
        <span className="skills__hint skills__mono">{item.path || "/"}</span>
        <span className="skills__hint">· {files} file{files === 1 ? "" : "s"}</span>
        <span className={`work-badge work-badge--${item.licence.allowed ? "active" : "attention"}`}>
          {item.licence.spdx ?? "No licence"}{item.licence.allowed ? "" : " · not allowed"}
        </span>
        {(item.scripts ?? []).map((script) => (
          <span key={script} className="work-badge work-badge--attention" title={script}>{script} · will be withheld</span>
        ))}
        {item.execution_keys?.length ? <span className="skills__hint">· stripped: {item.execution_keys.join(", ")}</span> : null}
        {item.security ? (
          <span className="skills__hint">· security {item.security.high} high · {item.security.medium} medium · {item.security.info} info</span>
        ) : null}
      </div>
      {item.description ? <div className="skills__import-meta skills__hint">{item.description}</div> : null}
      {spec ? (
        <div className="skills__import-meta skills__hint">
          <span className="skills__mono">{[spec.command, ...(spec.args ?? [])].filter(Boolean).join(" ")}</span>
          {spec.image ? <span>· image <span className="skills__mono">{spec.image}</span></span> : null}
          {spec.passthrough?.length ? <span className="skills__er">· {spec.passthrough.join(", ")}: never passed through</span> : null}
        </div>
      ) : null}
      {(item.spec_issues ?? []).map((issue) => (
        <div key={issue.code} className={`skills__import-meta skills__${issue.severity === "error" ? "er" : "wa"}`}>{issue.message}</div>
      ))}
      {offer.reason ? <div className="skills__import-meta skills__hint" data-testid="skill-import-reason">{offer.reason}</div> : null}
    </div>
  );
}
