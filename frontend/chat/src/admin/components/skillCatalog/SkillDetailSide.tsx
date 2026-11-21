import { useState } from "react";

import { TrustBadge } from "./SkillBadges";
import { saveTags, saveTracking } from "./skillCatalogApi";
import { refusalText, shortCommit, shortDigest } from "./skillCatalogModel";
import type { SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { formatWhen, ownerName, parseTags } from "./skillDetailModel";

// The detail page's right column (mock `renderDetail` aside): Catalog (category, tags edited inline, owner), the
// working version's availability (read-only: changing it is a draft change), Provenance with the tracking mode, and
// the security summary.
export function SkillDetailSide({ detail, version, onOpenCategory, onOpenSecurity, onChanged }: {
  detail: SkillDetail;
  version: SkillVersion | null;
  onOpenCategory: (key: string) => void;
  onOpenSecurity: () => void;
  onChanged: (message: string) => Promise<void>;
}) {
  const [editingTags, setEditingTags] = useState(false);
  const [tagText, setTagText] = useState(detail.tags.join(", "));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const mcp = detail.kind === "mcp_server";
  const category = detail.category;
  const summary = version?.security_report.summary ?? { high: 0, medium: 0, info: 0 };

  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      setEditingTags(false);
      await onChanged(done);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="admin-panel__stack" data-testid="skill-detail-side">
      <section className="work-detail__section">
        <h3>Catalog</h3>
        <dl className="work-detail__kv">
          <dt>Type</dt><dd>{mcp ? "MCP server entry (from a plugin)" : "Skill (Agent Skills format)"}</dd>
          <dt>Category</dt>
          <dd><CategoryLink category={category} onOpen={onOpenCategory} /></dd>
          <dt>Tags</dt>
          <dd>
            <TagsField tags={detail.tags} editing={editingTags} text={tagText} busy={busy} onText={setTagText}
              onEdit={() => setEditingTags(true)}
              onSave={() => void act(() => saveTags(detail.id, parseTags(tagText)), "Tags saved.")}
              onCancel={() => { setEditingTags(false); setTagText(detail.tags.join(", ")); }} />
          </dd>
          <dt>Roles</dt><dd>{version?.extension?.allowed_roles?.length ? version.extension.allowed_roles.join(", ") : "every role"}</dd>
          <dt>Owner</dt><dd>{ownerName(detail)}</dd>
        </dl>
      </section>

      <AvailabilitySection mcp={mcp} name={detail.name} version={version} />

      <ProvenanceSection detail={detail} version={version} busy={busy}
        onTracking={(mode) => void act(() => saveTracking(detail.id, mode), "Tracking saved.")} />

      <SecuritySummary summary={summary} onOpenSecurity={onOpenSecurity} />
      {problem ? <p className="policies__warn" role="alert">{problem}</p> : null}
    </aside>
  );
}

function AvailabilitySection({ mcp, name, version }: { mcp: boolean; name: string; version: SkillVersion | null }) {
  return (
    <section className="work-detail__section">
      <h3>Available in</h3>
      <LockedToggle label="Platform chat" hint={mcp ? "Not available: a local process (stdio) cannot run in the platform" : "Instructions and references (scripts never run in chat)"}
        on={Boolean(version?.available_platform_chat)} />
      <LockedToggle label="octryx-claude" hint={mcp ? "Added to the session plugin's .mcp.json where the MCP policy allows it" : `Delivered as /octryx:${name}`}
        on={Boolean(version?.available_octryx_claude)} />
      <p className="skills__hint">Changing availability is a draft change (it is part of the reviewed version).</p>
    </section>
  );
}

function SecuritySummary({ summary, onOpenSecurity }: { summary: SkillVersion["security_report"]["summary"]; onOpenSecurity: () => void }) {
  return (
    <section className="work-detail__section">
      <h3>Security review</h3>
      <div className="policies__row" style={{ flexWrap: "wrap" }}>
        <span className={`work-badge ${summary.high ? "work-badge--danger" : "work-badge--active"}`}>{summary.high} high</span>
        <span className={`work-badge ${summary.medium ? "work-badge--attention" : "work-badge--active"}`}>{summary.medium} medium</span>
        <span className="work-badge work-badge--neutral">{summary.info} info</span>
      </div>
      <button type="button" className="skills__plain" data-testid="skill-detail-open-findings" onClick={onOpenSecurity}>Open findings</button>
    </section>
  );
}

function CategoryLink({ category, onOpen }: { category: SkillDetail["category"]; onOpen: (key: string) => void }) {
  if (!category) return <>—</>;
  return (
    <button type="button" className="admin-policy-chip" data-testid="skill-detail-category"
      onClick={() => onOpen(category.key)}>{category.path.join(" / ")}</button>
  );
}

function LockedToggle({ label, hint, on }: { label: string; hint: string; on: boolean }) {
  return (
    <div className="skills__toggle">
      <span>{label}<small>{hint}</small></span>
      <span role="switch" aria-checked={on} aria-readonly="true" aria-label={label} className={`skills__switch is-locked${on ? " is-on" : ""}`} />
    </div>
  );
}

function TagsField({ tags, editing, text, busy, onText, onEdit, onSave, onCancel }: {
  tags: string[];
  editing: boolean;
  text: string;
  busy: boolean;
  onText: (value: string) => void;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  if (!editing) {
    return (
      <span className="policies__row" style={{ flexWrap: "wrap" }}>
        {tags.map((tag) => <span key={tag} className="skills__tag">#{tag}</span>)}
        {tags.length ? null : <span className="admin-panel__cell--muted">none</span>}
        <button type="button" className="skills__plain" data-testid="skill-detail-tags-edit" onClick={onEdit}>Edit</button>
      </span>
    );
  }
  return (
    <>
      <input className="skill-detail__tags-input" value={text} aria-label="Tags" placeholder="Tags, separated by commas"
        data-testid="skill-detail-tags-input" onChange={(event) => onText(event.target.value)} />
      <div className="policies__row" style={{ marginTop: ".35rem" }}>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy} data-testid="skill-detail-tags-save"
          onClick={onSave}>Save</button>
        <button type="button" className="admin-panel__action-btn" disabled={busy}
          onClick={onCancel}>Cancel</button>
      </div>
    </>
  );
}

function ProvenanceSection({ detail, version, busy, onTracking }: {
  detail: SkillDetail;
  version: SkillVersion | null;
  busy: boolean;
  onTracking: (mode: "pinned" | "follow") => void;
}) {
  const status = detail.upstream_status;
  return (
    <section className="work-detail__section">
      <h3>Provenance</h3>
      <dl className="work-detail__kv">
        <dt>Source</dt>
        <dd>{detail.source ? <><span className="skills__mono">{detail.source.label}</span> <TrustBadge source={detail.source} /></> : "Written here"}</dd>
        {detail.source?.url ? <><dt>URL</dt><dd className="skills__mono">{detail.source.url}{detail.source.ref ? ` @ ${detail.source.ref}` : ""}</dd></> : null}
        {detail.upstream_path ? (
          <><dt>Path</dt><dd className="skills__mono">{detail.upstream_path}
            {status?.path_moved ? <div className="policies__sub">folder moved to {status.path_moved.to}</div> : null}</dd></>
        ) : null}
        {detail.source ? (
          <>
            <dt>Upstream</dt><dd className="skills__mono">{shortCommit(status?.current_commit ?? version?.upstream?.commit ?? detail.pinned_commit)}</dd>
            <dt>Latest</dt>
            <dd className="skills__mono">{shortCommit(status?.latest_commit)}{" "}
              {status?.update_available ? <span className="work-badge work-badge--attention">new</span> : null}
              {status?.checked_at ? <div className="policies__sub">checked {formatWhen(status.checked_at)}</div> : null}</dd>
            <dt>Tracking</dt>
            <dd>
              <select className="admin-users__toolbar-select" value={detail.tracking_mode ?? "pinned"} disabled={busy} aria-label="Tracking"
                style={{ minHeight: "1.7rem", fontSize: "var(--ds-text-xs)", maxWidth: "100%" }} data-testid="skill-detail-tracking"
                onChange={(event) => onTracking(event.target.value as "pinned" | "follow")}>
                <option value="follow">Follow upstream{detail.source.ref ? ` (${detail.source.ref})` : ""}</option>
                <option value="pinned">Pinned to {shortCommit(detail.pinned_commit ?? status?.current_commit)}</option>
              </select>
            </dd>
          </>
        ) : null}
        <dt>Licence</dt><dd>{version?.licence_spdx ? <span className="work-badge work-badge--neutral">{version.licence_spdx}</span> : "—"}</dd>
        <dt>Digest</dt><dd className="skills__mono">{shortDigest(version?.bundle_digest)} (bundle)</dd>
      </dl>
    </section>
  );
}
