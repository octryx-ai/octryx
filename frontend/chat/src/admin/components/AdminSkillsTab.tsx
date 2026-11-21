import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { SegmentedTabs } from "../../layout/SegmentedTabs";

import { useAdminNavigation } from "../adminNavigation";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import { ApprovalRuleBadge } from "./approvalRule/ApprovalRuleBadge";
import { useApprovalRule } from "./approvalRule/approvalRule";
import { SettingsDrawer } from "./projectsTab/SettingsDrawer";
import { SkillCatalogList } from "./skillCatalog/SkillCatalogList";
import { SkillCategoriesTab } from "./skillCatalog/SkillCategoriesTab";
import { SkillDetailPage } from "./skillCatalog/SkillDetailPage";
import { type DetailTab } from "./skillCatalog/useSkillDetail";
import { SkillEditorPage } from "./skillCatalog/SkillEditorPage";
import { SkillImportDrawer } from "./skillCatalog/SkillImportDrawer";
import { SkillReviewDrawer } from "./skillCatalog/SkillReviewDrawer";
import { SkillSourcesTab } from "./skillCatalog/SkillSourcesTab";
import { SkillUpdateReview } from "./skillCatalog/SkillUpdateReview";
import { SkillUsageTab } from "./skillCatalog/SkillUsageTab";
import { loadCategories, loadSkills } from "./skillCatalog/skillCatalogApi";
import { refusalText } from "./skillCatalog/skillCatalogModel";
import type { CategoryCatalog, SkillList } from "./skillCatalog/skillCatalogTypes";
import "./adminChannels.css";
import "./policyEngine/policiesPage.css";
import "./policyEngine/policyDrawers.css";
import "./skillCatalog/skillsPage.css";

type PageTab = "catalog" | "categories" | "sources" | "usage";
const TABS: { id: PageTab; label: string }[] = [
  { id: "catalog", label: "Catalog" },
  { id: "categories", label: "Categories" },
  { id: "sources", label: "Sources & updates" },
  { id: "usage", label: "Usage" },
];
type View =
  | { kind: "tabs" }
  | { kind: "detail"; skillId: string; sub?: DetailTab }
  | { kind: "editor"; skillId: string | null }
  | { kind: "update"; skillId: string };
type Drawer = { kind: "help" } | { kind: "import" } | { kind: "review"; skillId: string } | null;

// Agents & workflows → Skills : the catalog
// status in the header, the tabs Catalog / Categories / Sources & updates / Usage, and the full-page detail, editor
// and update review. Every write goes through the governed lifecycle (draft → four-eyes review → published).
export function AdminSkillsTab(_props: { ctx?: Record<string, unknown> }) {
  const { openAdminTab } = useAdminNavigation();
  const [tab, setTab] = useState<PageTab>("catalog");
  const [view, setView] = useState<View>({ kind: "tabs" });
  const [drawer, setDrawer] = useState<Drawer>(null);
  // Bumped by a review decision (publish, approve, reject) so an open detail page reloads its own state.
  const [detailRevision, setDetailRevision] = useState(0);
  const [list, setList] = useState<SkillList | null>(null);
  const [categories, setCategories] = useState<CategoryCatalog | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const approvalRule = useApprovalRule();

  const load = useCallback(async () => {
    try {
      const [skills, tree] = await Promise.all([loadSkills(), loadCategories()]);
      setList(skills as SkillList);
      setCategories(tree as CategoryCatalog);
      setProblem(null);
    } catch (error) {
      setProblem(refusalText(error));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (problem && !list) return <p className="workspace-classification__message" role="alert" data-testid="skills-error">{problem}</p>;
  if (!list || !categories) return <p className="admin-panel__hint" role="status">Loading the skill catalog…</p>;

  const openSkill = (skillId: string, sub?: DetailTab) => { setDrawer(null); setView({ kind: "detail", skillId, sub }); };
  const showTab = (next: PageTab) => { setView({ kind: "tabs" }); setTab(next); };
  const openCategory = (key: string) => { setCategoryFilter(key); showTab("catalog"); };
  const { counts } = list;

  return (
    <div className="skills policies" data-testid="skills-page">
      <SkillsHeader counts={counts} approvalRule={approvalRule} onStatus={() => showTab(counts.updates ? "sources" : "catalog")}
        onHelp={() => setDrawer({ kind: "help" })} />

      {view.kind === "tabs" ? (
        <SkillTabsView tab={tab} showTab={showTab} list={list} categories={categories} categoryFilter={categoryFilter}
          setCategoryFilter={setCategoryFilter} openSkill={openSkill} openCategory={openCategory} setView={setView}
          setDrawer={setDrawer} load={load} />
      ) : (
        <SkillPageView view={view} categories={categories} detailRevision={detailRevision} setView={setView}
          setDrawer={setDrawer} load={load} openCategory={openCategory} openAdminTab={openAdminTab} />
      )}

      <SkillsDrawerSlot drawer={drawer} categories={categories} setDrawer={setDrawer} showTab={showTab} openSkill={openSkill}
        load={load} setDetailRevision={setDetailRevision} openAdminTab={openAdminTab} />
    </div>
  );
}

type SetView = (view: View) => void;
type SetDrawer = (drawer: Drawer) => void;
type OpenAdminTab = ReturnType<typeof useAdminNavigation>["openAdminTab"];

/** The catalog status card (opens Sources when updates wait), the approval rule and Help. */
function SkillsHeader({ counts, approvalRule, onStatus, onHelp }: {
  counts: SkillList["counts"];
  approvalRule: ReturnType<typeof useApprovalRule>;
  onStatus: () => void;
  onHelp: () => void;
}) {
  return (
    <AdminHeaderActions>
      <button type="button" className="policies__status-card" title="Catalog status" data-testid="skills-status-card"
        onClick={onStatus}>
        <span className="policies__status-dot policies__status-dot--enforce" />
        <span>{counts.published} published</span>
        <span className="policies__status-sep" />
        <span>{counts.drafts} draft{counts.drafts === 1 ? "" : "s"} · {counts.in_review} in review</span>
        {counts.updates ? (
          <>
            <span className="policies__status-sep" />
            <span className="skills__wa">{counts.updates} update{counts.updates === 1 ? "" : "s"} available</span>
          </>
        ) : null}
      </button>
      <ApprovalRuleBadge rule={approvalRule} />
      <button type="button" className="admin-panel__action-btn" title="Help for this page" data-testid="skills-help"
        onClick={onHelp}>? Help</button>
    </AdminHeaderActions>
  );
}

/** A skill's full page: its detail, its editor or the review of an upstream update. */
function SkillPageView({ view, categories, detailRevision, setView, setDrawer, load, openCategory, openAdminTab }: {
  view: Exclude<View, { kind: "tabs" }>;
  categories: CategoryCatalog;
  detailRevision: number;
  setView: SetView;
  setDrawer: SetDrawer;
  load: () => Promise<void>;
  openCategory: (key: string) => void;
  openAdminTab: OpenAdminTab;
}) {
  return view.kind === "detail" ? (
    <SkillDetailPage skillId={view.skillId} initialSub={view.sub} categories={categories} revision={detailRevision}
      onBack={() => { setView({ kind: "tabs" }); void load(); }}
      onEdit={(skillId) => setView({ kind: "editor", skillId })}
      onReviewUpdate={(skillId) => setView({ kind: "update", skillId })}
      onOpenReview={(skillId) => setDrawer({ kind: "review", skillId })}
      onOpenCategory={openCategory}
      onOpenWorkspaces={() => openAdminTab("projects")}
      onChanged={load} />
  ) : view.kind === "editor" ? (
    <SkillEditorPage skillId={view.skillId} categories={categories}
      onCancel={() => (view.skillId ? setView({ kind: "detail", skillId: view.skillId }) : setView({ kind: "tabs" }))}
      onSaved={(skillId) => { void load(); setView({ kind: "detail", skillId }); }}
      onOpenReview={(skillId) => { void load(); setView({ kind: "detail", skillId }); setDrawer({ kind: "review", skillId }); }} />
  ) : (
    <SkillUpdateReview skillId={view.skillId}
      onBack={() => setView({ kind: "detail", skillId: view.skillId })}
      onOpenReview={(skillId) => setDrawer({ kind: "review", skillId })}
      onChanged={load} />
  );
}

/** The tabs Catalog / Categories / Sources & updates / Usage and the open tab. */
function SkillTabsView({ tab, showTab, list, categories, categoryFilter, setCategoryFilter, openSkill, openCategory, setView,
  setDrawer, load }: {
  tab: PageTab;
  showTab: (next: PageTab) => void;
  list: SkillList;
  categories: CategoryCatalog;
  categoryFilter: string;
  setCategoryFilter: (key: string) => void;
  openSkill: (skillId: string, sub?: DetailTab) => void;
  openCategory: (key: string) => void;
  setView: SetView;
  setDrawer: SetDrawer;
  load: () => Promise<void>;
}) {
  return (
    <>
      <SegmentedTabs label="Skills views" idPrefix="skills" value={tab} testId="skills-tabs"
        onChange={(key) => showTab(key as PageTab)}
        tabs={TABS.map((item) => ({ key: item.id, label: item.label, testId: `skills-tab-${item.id}` }))} />
      {tab === "catalog" ? (
        <SkillCatalogList list={list} categories={categories} categoryFilter={categoryFilter}
          onCategoryFilter={setCategoryFilter}
          onOpen={openSkill}
          onNew={() => setView({ kind: "editor", skillId: null })}
          onImport={() => setDrawer({ kind: "import" })}
          onReviewUpdate={(skillId) => setView({ kind: "update", skillId })} />
      ) : tab === "categories" ? (
        <SkillCategoriesTab categories={categories} onChanged={load} onOpenCategory={openCategory} />
      ) : tab === "sources" ? (
        <SkillSourcesTab rows={list.items} onChanged={load} onOpenSkill={openSkill}
          onReviewUpdate={(skillId) => setView({ kind: "update", skillId })} />
      ) : (
        <SkillUsageTab rows={list.items} onOpenSkill={openSkill} />
      )}
    </>
  );
}

/** The open drawer: help, import or the review of a skill. */
function SkillsDrawerSlot({ drawer, categories, setDrawer, showTab, openSkill, load, setDetailRevision, openAdminTab }: {
  drawer: Drawer;
  categories: CategoryCatalog;
  setDrawer: SetDrawer;
  showTab: (next: PageTab) => void;
  openSkill: (skillId: string, sub?: DetailTab) => void;
  load: () => Promise<void>;
  setDetailRevision: Dispatch<SetStateAction<number>>;
  openAdminTab: OpenAdminTab;
}) {
  return drawer?.kind === "help" ? (
    <SkillsHelpDrawer onClose={() => setDrawer(null)}
      onSources={() => { setDrawer(null); showTab("sources"); }}
      onWorkspaces={() => { setDrawer(null); openAdminTab("projects"); }} />
  ) : drawer?.kind === "import" ? (
    <SkillImportDrawer categories={categories} onClose={() => setDrawer(null)}
      onImported={(skillIds) => { setDrawer(null); void load(); if (skillIds.length === 1) openSkill(skillIds[0]); }} />
  ) : drawer?.kind === "review" ? (
    <SkillReviewDrawer skillId={drawer.skillId} onClose={() => setDrawer(null)}
      onChanged={() => { void load(); setDetailRevision((value) => value + 1); }} />
  ) : null;
}

function SkillsHelpDrawer({ onClose, onSources, onWorkspaces }: { onClose: () => void; onSources: () => void; onWorkspaces: () => void }) {
  return (
    <SettingsDrawer eyebrow="Help" title="Skills" size="detail" onClose={onClose}>
      <div className="skills__help" data-testid="skills-help-drawer">
        <section className="work-detail__section">
          <h3>What a skill is</h3>
          <p>A folder in the open <b>Agent Skills</b> format: a <span className="admin-policy-inline-code">SKILL.md</span> with a
            name and a description, plus optional reference files. The agent sees only the name and description until a task
            matches; then it loads the instructions, and reference files only when it needs them.</p>
        </section>
        <section className="work-detail__section">
          <h3>Where skills appear</h3>
          <ul>
            <li><b>Platform chat</b>: agents find assigned skills with <span className="admin-policy-inline-code">skill_search</span> and
              load them with <span className="admin-policy-inline-code">skill_get</span>.</li>
            <li><b>octryx-claude</b>: the launcher delivers the Workspace&apos;s assigned skills as the <span className="admin-policy-inline-code">octryx</span> plugin
              at every session start; they are invoked as <span className="admin-policy-inline-code">/octryx:&lt;skill&gt;</span> or by the model.</li>
          </ul>
        </section>
        <section className="work-detail__section">
          <h3>Plugins that are not skills</h3>
          <p>A Claude Code plugin can bring skills, commands, agents, hooks and MCP servers. The catalog imports the <b>skills</b>;
            an <b>MCP server</b> becomes a reviewed MCP server entry that only runs where the Workspace MCP policy allows it.
            Commands, agents and hooks are listed and never imported.</p>
        </section>
        <section className="work-detail__section">
          <h3>Publishing</h3>
          <p>Edits and upstream updates always create a draft. A draft is published only after a second platform admin approves
            it (four-eyes). Published versions are immutable; rollback creates a new draft from an earlier version.</p>
        </section>
        <section className="work-detail__section">
          <h3>Skills never widen permissions</h3>
          <p><span className="admin-policy-inline-code">allowed-tools</span>, <span className="admin-policy-inline-code">hooks</span> and
            shell blocks in a SKILL.md are not delivered. Scripts are withheld unless a platform admin allows them for that version.
            Every tool call still goes through the Workspace tool policy and the platform policies.</p>
        </section>
        <section className="work-detail__section">
          <h3>Updates from upstream</h3>
          <p>&quot;Check for updates&quot; reads the source. &quot;Review update&quot; shows the upstream changes and your local
            customizations side by side; non-overlapping changes are merged, overlapping ones are conflicts you resolve before
            submitting.</p>
        </section>
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" onClick={onSources}>Sources &amp; updates</button>
          <button type="button" className="admin-panel__action-btn" onClick={onWorkspaces}>Assign skills to a Workspace</button>
        </div>
      </div>
    </SettingsDrawer>
  );
}
