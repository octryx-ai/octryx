import { useEffect, useRef, useState } from "react";

import type { ProjectOption } from "../../chatOptionTypes";
import type { WorkFilters as WorkFiltersValue } from "./workTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { EMPTY_WORK_FILTERS, WORK_AUTOMATION_FILTERS } from "./workUtils";
import { workStateFilterLabels } from "./workBoardColumns";
import { sourceLabel } from "./incident/workSourceModel";

// The Work items filter bar and summary metrics (split out of WorkAreaWorkspace.tsx).

export function WorkFiltersBar({
  filters,
  setFilters,
  options,
  assigneeLabels,
  workflows,
}: {
  filters: WorkFiltersValue;
  setFilters: (filters: WorkFiltersValue) => void;
  options: Record<string, string[]>;
  projects: ProjectOption[];
  assigneeLabels: Record<string, string>;
  workflows: WorkWorkflowDefinition[];
}) {
  const update = (patch: Partial<WorkFiltersValue>) => setFilters({ ...filters, ...patch });
  // Search and the two most used filters stay visible; the rest sit behind
  // "More filters" with a count, so the board starts within the first screen.
  const secondaryActive = [
    filters.sourceType, filters.sourceProject, filters.workState, filters.syncState, filters.automationMode,
  ].filter(Boolean).length + filters.labels.length + filters.fixVersions.length + filters.sprints.length;
  return (
    <div className="work-area__filters work-area__filters--compact">
      <input
        value={filters.search}
        onChange={(event) => update({ search: event.target.value })}
        placeholder="Search work…"
        aria-label="Search work"
      />
      <MultiFilterSelect
        label="Jira status"
        values={options.sourceStatuses}
        selected={filters.sourceStatuses}
        onChange={(value) => update({ sourceStatuses: value })}
      />
      <MultiFilterSelect
        label="Assignee"
        labels={assigneeLabels}
        values={options.assignees}
        selected={filters.assignees}
        onChange={(value) => update({ assignees: value })}
      />
      <details className="work-area__more-filters">
        <summary className="work-area__button">More filters{secondaryActive ? ` (${secondaryActive})` : ""}</summary>
        <div className="work-area__more-filters-body">
          <FilterSelect label="Source" value={filters.sourceType} values={options.sourceTypes}
            labels={Object.fromEntries(options.sourceTypes.map((value) => [value, sourceLabel(value)]))}
            onChange={(value) => update({ sourceType: value })} />
          <FilterSelect label="Jira project" value={filters.sourceProject} values={options.sourceProjects} onChange={(value) => update({ sourceProject: value })} />
          <FilterSelect label="Work state" value={filters.workState} values={options.workStates}
            labels={workStateFilterLabels(options.workStates, workflows)}
            onChange={(value) => update({ workState: value })} />
          <FilterSelect label="Sync" value={filters.syncState} values={options.syncStates} onChange={(value) => update({ syncState: value })} />
          <FilterSelect
            label="Automation"
            value={filters.automationMode}
            values={WORK_AUTOMATION_FILTERS.map((entry) => entry.value)}
            labels={Object.fromEntries(WORK_AUTOMATION_FILTERS.map((entry) => [entry.value, entry.label]))}
            onChange={(value) => update({ automationMode: value })}
          />
          <MultiFilterSelect label="Labels" values={options.labels} selected={filters.labels} onChange={(value) => update({ labels: value })} />
          <MultiFilterSelect label="Fix version" values={options.fixVersions} selected={filters.fixVersions} onChange={(value) => update({ fixVersions: value })} />
          <MultiFilterSelect label="Sprint" values={options.sprints} selected={filters.sprints} onChange={(value) => update({ sprints: value })} />
        </div>
      </details>
      <button type="button" className="work-area__button" onClick={() => setFilters(EMPTY_WORK_FILTERS)}>
        Clear
      </button>
    </div>
  );
}

function MultiFilterSelect({
  label,
  values,
  labels,
  selected,
  onChange,
}: {
  label: string;
  values: string[];
  // Shown names for the values (people ids).
  labels?: Record<string, string>;
  selected: string[];
  onChange: (value: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectedSet = new Set(selected);
  const summary = selected.length === 0 ? label : `${label}: ${selected.length}`;

  useEffect(() => {
    if (!open) return undefined;

    function closeOnOutsideClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function toggleValue(value: string) {
    const next = selectedSet.has(value) ? selected.filter((item) => item !== value) : [...selected, value];
    onChange(next);
  }

  return (
    <div className="work-filter-multi" ref={containerRef}>
      <button
        type="button"
        className="work-filter-multi__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{summary}</span>
        {/* The chevron of a select, not a literal "v". */}
        <svg className={`work-filter-multi__chevron${open ? " work-filter-multi__chevron--open" : ""}`} viewBox="0 0 20 20"
          aria-hidden="true" data-testid="work-filter-chevron">
          <path d="M5.75 7.75 10 12.25 14.25 7.75" />
        </svg>
      </button>
      {open ? (
        <div className="work-filter-multi__menu" role="listbox" aria-label={label}>
          <button type="button" className="work-filter-multi__clear" onClick={() => onChange([])}>
            Clear {label.toLowerCase()}
          </button>
          {values.length === 0 ? <span className="work-filter-multi__empty">No values</span> : null}
          {values.map((entry) => (
            <label key={entry} className="work-filter-multi__option admin-panel__checkbox">
              <input
                type="checkbox"
                checked={selectedSet.has(entry)}
                onChange={() => toggleValue(entry)}
              />
              <span>{labels?.[entry] || entry}</span>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  values,
  labels,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  labels?: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <select className="admin-users__toolbar-select" value={value} aria-label={label} onChange={(event) => onChange(event.target.value)}>
      <option value="">{label}</option>
      {values.map((entry) => (
        <option key={entry} value={entry}>
          {labels?.[entry] || entry}
        </option>
      ))}
    </select>
  );
}
