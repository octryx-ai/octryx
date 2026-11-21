import { useEffect, useRef, useState } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import "../settingsKit/settingsKit.css";
import { ProjectSettingsSectionContent } from "./ProjectSettingsSectionContent";
import {
  PROJECT_SETTINGS_GROUPS,
  projectSettingsGroupOf,
  projectSettingsSectionLabel,
  resolveProjectSettingsTab,
  type ProjectSettingsTab,
} from "./projectSettingsSections";
import { takeWorkspaceSettingsRequest, type WorkspaceSettingsFocus } from "./workspaceSettingsLink";

// A Workspace's settings page: breadcrumb back to
// the list, the Workspace's sections as the one tab style (SegmentedTabs) and the active section.
// review: at most two rows that fit at 1280 — the section groups, then the group's sections (small) when it
// has more than one.
export function WorkspaceSettingsPage({ ctx, project, isAdmin, onBack }: {
  ctx: Record<string, unknown>;
  project: AdminProjectQuality;
  isAdmin: boolean;
  onBack: () => void;
}) {
  const [section, setSection] = useState<ProjectSettingsTab>("overview");
  const [focus, setFocus] = useState<WorkspaceSettingsFocus | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  // A link from Work, Coding or chat Agents opens the requested section once (workspaceSettingsLink).
  useEffect(() => {
    const requested = takeWorkspaceSettingsRequest(project.id);
    setSection((requested && resolveProjectSettingsTab(requested.section)) || "overview");
    setFocus(requested?.focus ?? null);
    // A link to a section shows it: scroll the section into view once it has rendered.
    if (requested) window.setTimeout(() => panelRef.current?.scrollIntoView?.({ block: "start" }), 0);
  }, [project.id]);
  const group = projectSettingsGroupOf(section);

  return (
    <div className="sk-page" data-testid="workspace-settings-page">
      <div className="sk-row">
        <button type="button" className="sk-crumb" data-testid="workspace-back" onClick={onBack}>Workspaces /</button>
        <span className="sk-name">{project.name}</span>
      </div>
      <div className="workspace-settings__sections">
        <SegmentedTabs label="Workspace settings" idPrefix="workspace-group" value={group.key}
          onChange={(key) => setSection(PROJECT_SETTINGS_GROUPS.find((item) => item.key === key)?.sections[0] ?? "overview")}
          tabs={PROJECT_SETTINGS_GROUPS.map((item) => ({
            key: item.key, label: item.label,
            testId: item.sections.length === 1 ? `workspace-section-${item.sections[0]}` : `workspace-group-${item.key}`,
          }))} />
        {group.sections.length > 1 ? (
          <SegmentedTabs size="small" label={`${group.label} sections`} idPrefix="workspace-section" value={section}
            onChange={(key) => setSection(key as ProjectSettingsTab)}
            tabs={group.sections.map((key) => ({ key, label: projectSettingsSectionLabel(key), testId: `workspace-section-${key}` }))} />
        ) : null}
      </div>
      <div ref={panelRef} className="project-settings-content" role="tabpanel"
        id={group.sections.length > 1 ? `workspace-section-panel-${section}` : `workspace-group-panel-${group.key}`}
        aria-labelledby={group.sections.length > 1 ? `workspace-section-tab-${section}` : `workspace-group-tab-${group.key}`}>
        <ProjectSettingsSectionContent ctx={ctx} project={project} section={section} isAdmin={isAdmin} onOpenSection={setSection}
          focus={focus} />
      </div>
    </div>
  );
}
