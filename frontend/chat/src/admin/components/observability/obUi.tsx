import type { ReactNode } from "react";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { sentenceCase } from "../agentsWorkflows/awBadges";

// Shared presentation for the Observability pages (approved mock, WP observability audit).
// Status is never colour alone: every badge carries an icon character and a label.

export type BadgeTone = "active" | "running" | "attention" | "danger" | "neutral";

export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <span className={`work-badge work-badge--${tone}`}>{typeof children === "string" ? sentenceCase(children) : children}</span>;
}

export type ProjectOption = { id: string; name: string };

export function WorkspaceSelect({
  projects,
  value,
  onChange,
}: {
  projects: ProjectOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select
      className="admin-users__toolbar-select"
      aria-label="Workspace"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">All Workspaces</option>
      {projects.map((project) => (
        <option key={project.id} value={project.id}>
          {project.name}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  // The one tab style: SegmentedTabs, small, as a filter in the toolbar.
  return (
    <SegmentedTabs size="small" label={label} idPrefix={`ob-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      value={String(value)}
      onChange={(key) => { const option = options.find((entry) => String(entry.value) === key); if (option) onChange(option.value); }}
      tabs={options.map((option) => ({ key: String(option.value), label: option.label }))} />
  );
}
