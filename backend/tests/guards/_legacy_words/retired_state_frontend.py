from __future__ import annotations

from tests.guards._legacy_words._build import concept, within

RETIRED_STATE_FRONTEND = concept(
    "'retired': the end state of a governed lifecycle (draft -> in_review -> published -> retired) and of synced "
    "knowledge items and mirrored catalog items; a stored state, an API value and a UI label",
    *within("frontend/chat/src/admin/components/agentsTab/AgentSkillPreferencesField.tsx",
            "AgentSkillPreferencesField",
            "// Skills with a published or an open version; a retired-only skill has neither."),
    *within("frontend/chat/src/admin/components/agentsWorkflows/instructions/instructionsModel.ts", "statusLabel",
            ('if (row.status === "retired") return { label: "Retired", kind: "neutral" };', 2)),
    *within("frontend/chat/src/admin/components/agentsWorkflows/workflows/workflowsModel.ts", "statusLabel",
            ('if (row.status === "retired") return "Retired";', 2)),
    *within("frontend/chat/src/admin/components/dataClassification/ClassificationChangesTab.tsx",
            "ClassificationChangesTab",
            '{row.state === "retired" ? ('),
    *within("frontend/chat/src/admin/components/dataClassification/ClassificationLevelDrawer.tsx",
            "ClassificationEditLevelDrawer",
            '{level.builtin ? <p className="sk-hint">Built-in levels can be renamed and described, never '
            "retired.</p> : null}"),
    *within("frontend/chat/src/admin/components/dataClassification/classificationLevelCatalog.ts", "newLevelChecks",
            '{ state: "info", text: "No Workspace uses this level yet; it can be retired until one does" },'),
    *within("frontend/chat/src/admin/components/dataClassification/classificationVersionsModel.ts", "STATE_BADGE",
            ('retired: { badge: "work-badge--neutral", label: "Retired" },', 2)),
    *within("frontend/chat/src/admin/components/governedRegistry/GovernedDrawer.tsx", "STATE_BADGE",
            'retired: "inactive",'),
    *within("frontend/chat/src/admin/components/policyEngine/PolicyLifecycleParts.tsx", "LifecycleHistory",
            '{row.state === "retired" ? <button type="button" className="admin-panel__action-btn" '
            "data-testid={`lifecycle-rollback-${row.version}`} disabled={busy || open}"),
    *within("frontend/chat/src/admin/components/policyEngine/PolicyLifecycleParts.tsx", "LifecycleReview",
            "// Every version with its state, note, author and reviewer; roll back a retired one, retire the "
            "published one."),
    *within("frontend/chat/src/admin/components/policyEngine/PolicyLifecycleParts.tsx", "LifecycleTimeline",
            '{step(2, "Published", `Test cases run again${published ? `; v${published.version} is retired` : '
            '""}`)}'),
    *within("frontend/chat/src/admin/components/policyEngine/PolicyLifecycleParts.tsx", "STATE_TONES",
            'const STATE_TONES: Record<string, string> = { draft: "attention", in_review: "running", published: '
            '"active", retired: "neutral" };'),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineStatus.ts", "STATE_LABELS",
            ('retired: "Retired",', 2)),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineVersions.ts", "REFUSALS",
            'policy_set_retire_requires_review: "The published version is retired only through review: publish an '
            'empty draft.",'),
    *within("frontend/chat/src/admin/components/promptCatalog/PromptDetailDrawer.tsx", "PromptContract",
            "// One System prompt text: its contract (placeholders), the shipped text, every version (global; "
            "retired"),
    *within("frontend/chat/src/admin/components/promptCatalog/PromptVersionActions.tsx", "VersionButtons",
            '{state !== "retired" ? ('),
    *within("frontend/chat/src/admin/components/promptCatalog/promptCatalogModel.ts", "TEXT",
            'prompt_version_retired: "This version is already retired.",'),
    *within("frontend/chat/src/admin/components/promptCatalog/promptCatalogTypes.ts", "PromptVersionState",
            'export type PromptVersionState = "draft" | "in_review" | "published" | "retired";'),
    *within("frontend/chat/src/admin/components/promptCatalog/usePromptCatalog.ts", "promptLifecycleActions",
            'retire: (versionId: string) => run("retire", () => api.retire(versionId), "Retired."),'),
    *within("frontend/chat/src/admin/components/skillCatalog/SkillCatalogList.tsx", "CatalogRow",
            (': <span className={stateBadge("retired")}>Retired</span>}', 2)),
    *within("frontend/chat/src/admin/components/skillCatalog/SkillDetailParts.tsx", "SkillDetailHead",
            ('{states.length ? null : <span className={stateBadge("retired")}>Retired</span>}', 2)),
    *within("frontend/chat/src/admin/components/skillCatalog/SkillVersionsTab.tsx", "SkillVersionsTab",
            '<p className="skills__hint skill-detail__gap">Same lifecycle as platform policies: draft → in review '
            "→ published → retired. Published"),
    *within("frontend/chat/src/admin/components/skillCatalog/SkillVersionsTab.tsx", "VersionActions",
            'const canRollback = !isPublished && (row.state === "published" || row.state === "retired");',
            "onClick={() => void act(() => retireVersion(detail.id, row.version), `v${row.version} "
            "retired.`)}>Retire v{row.version}</button>"),
    *within("frontend/chat/src/admin/components/skillCatalog/SkillVersionsTab.tsx", "VersionRow",
            '<tr className={row.state === "retired" ? "admin-panel__row--inactive" : undefined} '
            "data-testid={`skill-version-${row.version}`}>",
            "{row.retired_at ? <div>retired {formatWhen(row.retired_at)}</div> : null}"),
    *within("frontend/chat/src/admin/components/skillCatalog/skillCatalogModel.ts", "STATE_BADGES",
            "/** `work-badge` modifier of a version state (published active, draft attention, in review running, "
            "retired neutral). */",
            'const STATE_BADGES: Record<VersionState, string> = { draft: "attention", in_review: "running", '
            'published: "active", retired: "neutral" };'),
    *within("frontend/chat/src/admin/components/skillCatalog/skillCatalogModel.ts", "STATE_LABELS",
            ('export const STATE_LABELS: Record<VersionState, string> = { draft: "Draft", in_review: "In review", '
             'published: "Published", retired: "Retired" };', 2)),
    *within("frontend/chat/src/admin/components/skillCatalog/skillCatalogModel.ts", "versionLine",
            'return parts.length ? parts.join(" · ") : "retired";'),
    *within("frontend/chat/src/admin/components/skillCatalog/skillCatalogRefusals.ts", "REFUSALS",
            'skill_version_retired: "This version is retired.",'),
    *within("frontend/chat/src/admin/components/skillCatalog/skillCatalogTypes.ts", "VersionState",
            'export type VersionState = "draft" | "in_review" | "published" | "retired";'),
    *within("frontend/chat/src/admin/components/skillCatalog/skillListModel.ts", "STATUS_OPTIONS",
            ('{ value: "retired", label: "Retired" },', 2)),
    *within("frontend/chat/src/admin/components/skillCatalog/skillListModel.ts", "StatusFilter",
            'export type StatusFilter = "" | "published" | "draft" | "in_review" | "update" | "retired";'),
    *within("frontend/chat/src/admin/components/skillCatalog/skillListModel.ts", "countInCategory",
            "/** A row with neither a published nor an open version is retired. */"),
    *within("frontend/chat/src/admin/components/skillCatalog/skillListModel.ts", "matchesStatus",
            'case "retired": return isRetired(row);'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/KnowledgeConnectorRun.tsx", "COUNT_KEYS",
            'const COUNT_KEYS: OutcomeKind[] = ["created", "updated", "unchanged", "retired", "skipped", '
            '"failed", "deferred"];'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/KnowledgeConnectorRun.tsx", "OUTCOME_BADGE",
            'retired: "admin-panel__badge--inactive",'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/connectorFreshness.ts", "<module>",
            "// - the last run and its counts: `last_run.report` (created → new, updated → changed, retired → "
            "removed);"),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/connectorFreshness.ts", "runPageCounts",
            "removed: count(raw.retired),"),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/connectorTypes.ts", "OutcomeKind",
            'export type OutcomeKind = "created" | "updated" | "unchanged" | "retired" | "skipped" | "failed" | '
            '"deferred";'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/gitRepositoryReport.ts", "RARE_OUTCOMES",
            'const RARE_OUTCOMES = ["failed", "retired"] as const;'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/structuredGraphApi.ts", "LayerReport",
            "selected?: number; extracted?: number; already_current?: number; retired?: number; failed?: number;"),
)
