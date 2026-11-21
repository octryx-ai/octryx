import type { SourceConnector } from "./connectorTypes";
import type { ReleaseSyncState } from "./jiraReleasesContract";
import { draftFromBlock, newProductRow, unplacedErrors } from "./jiraReleasesModel";
import type { FieldErrors, ReleasesDraft } from "./jiraReleasesModel";
import { ReleaseProductsTable, ReleaseSectionsTable } from "./KnowledgeReleaseTables";
import { FieldError, ReleaseTagList } from "./KnowledgeReleaseTags";
import { useJiraReleasesDrawer, type Banner } from "./useJiraReleasesDrawer";
import "./jiraReleases.css";

const SYNC_BADGE: Record<ReleaseSyncState["state"], string> = {
  active: "active",
  needs_configuration: "warning",
  off: "inactive",
};

function SyncBadge({ sync }: { sync: ReleaseSyncState | undefined }) {
  const state = sync?.state ?? "off";
  return <span className={`admin-panel__badge admin-panel__badge--${SYNC_BADGE[state]}`}>{state.replace("_", " ")}</span>;
}

type Edit = (patch: Partial<ReleasesDraft>) => void;

// The four parts of a configured releases block.
function ReleaseBlockSections({ draft, projectKeys, errors, edit }: { draft: ReleasesDraft; projectKeys: string[]; errors: FieldErrors; edit: Edit }) {
  return (
    <>
      <section className="kr-section">
        <div className="kr-eyebrow">Products</div>
        <div className="kr-help">A mapped project's Jira versions become release notes of exactly that product.</div>
        <ReleaseProductsTable rows={draft.products} projectKeys={projectKeys} errors={errors}
          onChange={(products) => edit({ products })} />
      </section>
      <section className="kr-section">
        <div className="kr-eyebrow">Version name prefixes</div>
        <div className="kr-help">
          Literal text stripped from a version name before it is read as a version: “Release␣” turns
          “Release 2.4.20” into 2.4.20. A leading v before a digit needs no prefix. Spaces count.
        </div>
        <ReleaseTagList field="releases.version_name_prefixes" label="Version name prefixes" values={draft.prefixes}
          errors={errors} placeholder="e.g. Release (with its trailing space)" onChange={(prefixes) => edit({ prefixes })} />
      </section>
      <section className="kr-section">
        <div className="kr-eyebrow">Sections</div>
        <ReleaseSectionsTable rows={draft.sections} errors={errors} onChange={(sections) => edit({ sections })} />
      </section>
      <section className="kr-section">
        <div className="kr-eyebrow">Blocker priorities</div>
        <div className="kr-help">
          Exact Jira priority names (case-insensitive) that count as blockers in the live release status.
          Without any, the status reports no blockers and says so.
        </div>
        <ReleaseTagList field="releases.blocker_priorities" label="Blocker priorities" values={draft.blockerPriorities}
          errors={errors} placeholder="e.g. Blocker" onChange={(blockerPriorities) => edit({ blockerPriorities })} />
      </section>
    </>
  );
}

// The loaded connector: its sync state, the banner, the block (or the offer to set one up) and how saving works.
function ReleasesReadyBody({ connector, draft, saved, dirty, banner, errors, serverErrors, edit }: {
  connector: SourceConnector; draft: ReleasesDraft; saved: SourceConnector["scope"]["releases"] | null; dirty: boolean;
  banner: Banner; errors: FieldErrors; serverErrors: FieldErrors; edit: Edit;
}) {
  const unplaced = unplacedErrors(serverErrors, draft);
  return (
    <>
      <div className="kr-row" data-state="release-sync">
        <SyncBadge sync={connector.release_sync} />
        {dirty ? <span className="admin-panel__badge admin-panel__badge--info">unsaved changes</span> : null}
        {connector.state === "paused" ? <span className="admin-panel__badge admin-panel__badge--inactive">connector paused</span> : null}
      </div>
      {banner ? (
        <div className={`kr-alert kr-alert--${banner.kind}`} role={banner.kind === "error" ? "alert" : "status"}>
          <span>{banner.code ? <><code>{banner.code}</code> </> : null}{banner.text}</span>
        </div>
      ) : null}
      {unplaced.map(([path, code]) => <FieldError key={path} path={path} code={code} />)}
      {draft.enabled ? (
        <ReleaseBlockSections draft={draft} projectKeys={connector.scope.project_keys ?? []} errors={errors} edit={edit} />
      ) : (
        <div className="kr-empty" data-state="no-releases-block">
          <strong>{saved ? "Release notes will be switched off when you save." : "No releases block configured."}</strong>
          <span>Without it, this connector syncs issues only; its Jira versions do not become release notes.</span>
          <button type="button" className="admin-panel__action-btn"
            onClick={() => edit(saved ? draftFromBlock(saved) : { enabled: true, products: [newProductRow()] })}>
            {saved ? "Keep release notes" : "Set up release notes"}
          </button>
        </div>
      )}
      <div className="kr-help">
        Saving sends this connector's stored configuration back unchanged with only this block replaced. A changed
        block starts a new sync pass; if a schedule is on, you become its owner. The Jira credential stays in the
        Workspace connection: it is never shown here or sent from this page.
      </div>
    </>
  );
}

type Drawer = ReturnType<typeof useJiraReleasesDrawer>;

function ReleasesFooter({ drawer, onClose }: { drawer: Drawer; onClose: () => void }) {
  const { phase, draft, saving, dirty, close, edit, save } = drawer;
  if (drawer.confirmDiscard) {
    return (
      <>
        <span className="admin-panel__muted">Discard unsaved changes?</span>
        <span className="kr-drawer__footer-spacer" />
        <button type="button" className="admin-panel__action-btn" onClick={() => drawer.setConfirmDiscard(false)}>Keep editing</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={onClose}>Discard</button>
      </>
    );
  }
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={close}>Cancel</button>
      {phase === "ready" && draft.enabled ? (
        <button type="button" className="admin-panel__action-btn" disabled={saving} onClick={() => edit({ enabled: false })}>
          Switch off
        </button>
      ) : null}
      <span className="kr-drawer__footer-spacer" />
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={phase !== "ready" || saving || !dirty} onClick={() => void save()}>
        {saving ? "Saving…" : "Save"}
      </button>
    </>
  );
}

// The `releases` block of one Jira connector, edited in a right drawer. It reloads the connector on open, because
// the PUT replaces the whole configuration: the body is the freshly listed configuration with only the block
// replaced. The server is authoritative; its refusals are shown with their code next to the field they name.
export function KnowledgeJiraReleasesDrawer({ workspaceId, connectorKey, onClose, onSaved }: {
  workspaceId: string;
  connectorKey: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const drawer = useJiraReleasesDrawer(workspaceId, connectorKey, onClose, onSaved);
  const { phase, connector, close } = drawer;
  return (
    <div className="kr-drawer__backdrop" onClick={close}>
      <aside className="kr-drawer" role="dialog" aria-label={`Release notes of ${connectorKey}`} onClick={(event) => event.stopPropagation()}>
        <header className="kr-drawer__header">
          <div>
            <div className="kr-eyebrow">Jira connector · releases</div>
            <div className="kr-drawer__title">{connectorKey}</div>
          </div>
          <button type="button" className="kr-drawer__close" onClick={close} aria-label="Close">✕</button>
        </header>
        <div className="kr-drawer__body">
          {phase === "loading" ? <div className="admin-panel__hint" role="status">Loading…</div> : null}
          {phase === "missing" ? (
            <div className="kr-alert kr-alert--error" role="alert">This Jira connector no longer exists in the Workspace.</div>
          ) : null}
          {phase === "ready" && connector ? (
            <ReleasesReadyBody connector={connector} draft={drawer.draft} saved={drawer.saved} dirty={drawer.dirty} banner={drawer.banner}
              errors={drawer.errors} serverErrors={drawer.serverErrors} edit={drawer.edit} />
          ) : null}
        </div>
        <footer className="kr-drawer__footer">
          <ReleasesFooter drawer={drawer} onClose={onClose} />
        </footer>
      </aside>
    </div>
  );
}
