import { SkillSourceDrawer } from "./SkillSourceDrawer";
import { SkillSourceSettings } from "./SkillSourceSettings";
import { SourceTableRow, UploadsRow } from "./SkillSourcesParts";
import { checkAllSources } from "./skillCatalogApi";
import type { SkillRow } from "./skillCatalogTypes";
import { checkAllText, isUploadRow, sourceRows } from "./skillTabsModel";
import { useSkillSources } from "./useSkillSources";

// Skills → Sources & updates (WP 2.9, mock `#tab-sources`): the upstream sources skills were imported from,
// with trust, licence, tracking, the last check and its result, manual checks, and the scheduled-check settings.
// A check only reads the source; an update always becomes a draft that needs a second admin.
export function SkillSourcesTab({ rows, onChanged, onOpenSkill, onReviewUpdate }: {
  rows: SkillRow[];
  onChanged: () => void | Promise<void>;
  onOpenSkill: (skillId: string, sub?: "usage") => void;
  onReviewUpdate: (skillId: string) => void;
}) {
  const { sources, settings, setSettings, editing, setEditing, busy, message, load, check } = useSkillSources(onChanged);
  const upstream = (sources ?? []).filter((source) => source.kind !== "upload");
  const uploads = rows.filter(isUploadRow);

  return (
    <div data-testid="skills-sources">
      <div className="policies__flex-between" style={{ marginBottom: ".7rem" }}>
        <p className="admin-panel__hint">Upstream sources are Git repositories or plugin marketplaces skills (and MCP server entries)
          were imported from. A platform admin marks a source <b>Official</b> when it is the publisher&apos;s own repository or the
          official marketplace; the label is shown on every entry from it. Checking for updates only reads the source; an update
          always becomes a <b>draft</b> that is approved before it is published (Settings → Governance → Approval rule).</p>
        <span className="policies__row">
          <button type="button" className="admin-panel__action-btn" disabled={busy || !upstream.length} data-testid="sources-check-all"
            onClick={() => void check(checkAllSources, checkAllText)}>Check all now</button>
        </span>
      </div>
      {message ? (
        <p className={message.problem ? "workspace-classification__message" : "admin-panel__hint"} role={message.problem ? "alert" : "status"}
          data-testid="sources-message">{message.text}</p>
      ) : null}
      {sources === null && !message ? <p className="admin-panel__hint" role="status">Loading the sources…</p> : null}
      <div className="skills__scroll">
        <table className="admin-panel__table">
          <thead><tr><th>Source</th><th>Ref / path</th><th>Licence</th><th>Skills</th><th>Tracking</th><th>Last check</th><th>Status</th><th /></tr></thead>
          <tbody>
            {upstream.map((source) => (
              <SourceTableRow key={source.id} source={source} items={sourceRows(rows, source)} busy={busy} onOpenSkill={onOpenSkill}
                onReviewUpdate={onReviewUpdate} onCheck={(action, describe) => void check(action, describe)} onEdit={setEditing} />
            ))}
            {uploads.length ? <UploadsRow uploads={uploads} onOpenSkill={onOpenSkill} /> : null}
            {sources !== null && !upstream.length && !uploads.length ? (
              <tr><td colSpan={8}><div className="admin-panel__empty-state">No sources yet. Import a skill to add one.</div></td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {settings ? <SkillSourceSettings settings={settings} onSaved={setSettings} /> : null}

      {editing ? (
        <SkillSourceDrawer source={editing} onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await Promise.all([load(), onChanged()]); }} />
      ) : null}
    </div>
  );
}
