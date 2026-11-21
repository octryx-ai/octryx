import {
  setupText, type RepositorySource, type WorkspaceRepository,
} from "../../../admin/components/projectsTab/repositories/workspaceRepositoriesApi";
import { connectionTypeLabel, repositoryDisplayName, sourceRows, type RepositoryOverviewRow } from "./repositoryPresenter";

// Work › Repositories lists every repository the Workspace uses. Two reads meet here: the Workspace's repository
// records (`GET /workspaces/{ws}/repositories`, branch, owners, coding setup) and its Knowledge git sources
// (`GET /workspaces/{ws}/repositories/sources`), each of which can become a record.

/** The key two rows of one repository share: project/repository as people say it, case-insensitive. */
export function repositoryMatchKey(name: string): string {
  return repositoryDisplayName(name).toLowerCase();
}

function capitalised(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** The record's coding setup in words ("Build · test · lint", "Lint missing", "Not set up"). */
export function recordSetup(record: WorkspaceRepository): { text: string; missing: boolean } {
  const summary = record.coding_setup ?? { configured: [], missing: [] };
  const { text, missing } = setupText({ configured: summary.configured ?? [], missing: summary.missing ?? [] });
  return { text: capitalised(text || "not set up"), missing: missing || !text };
}

/** Where a record comes from, when no source row says it better. */
export function recordOrigin(record: WorkspaceRepository): { label: string; title: string } {
  const kind = record.source?.kind || record.provider || "";
  if (kind === "knowledge_source") return { label: "Knowledge source", title: "Created from a Knowledge git source." };
  if (!kind) return { label: "Repository record", title: "A repository record of this Workspace." };
  const label = connectionTypeLabel(kind);
  return { label, title: `A ${label} repository recorded under Admin › Workspace › Repositories.` };
}

function hasRecordShape(record: WorkspaceRepository): boolean {
  return typeof record?.id === "string" && typeof record?.name === "string";
}

/**
 * One row per repository: a Knowledge source row carries the branch and coding setup of the record that names the
 * same project/repository (then it is set up and opens its runs); a record no source names is listed on its own.
 * When several records name one repository, the first is listed.
 */
export function workspaceRepositoryRows(records: WorkspaceRepository[], sources: RepositorySource[]): RepositoryOverviewRow[] {
  const usable = records.filter(hasRecordShape);
  const byName = new Map<string, WorkspaceRepository>();
  for (const record of usable) {
    const key = repositoryMatchKey(record.name);
    if (!byName.has(key)) byName.set(key, record);
  }
  const joined = new Set<string>();
  const fromSources = sourceRows(sources).map((row): RepositoryOverviewRow => {
    const record = byName.get(repositoryMatchKey(row.path));
    if (!record) return { ...row, branch: null, setup: null, recordId: null };
    joined.add(record.id);
    return { ...row, canSetUp: false, branch: record.default_branch || null,
      branchFromSource: record.default_branch_from === "knowledge_source", setup: recordSetup(record), recordId: record.id };
  });
  const ownRecords = usable.filter((record) => !joined.has(record.id) && byName.get(repositoryMatchKey(record.name)) === record)
    .map((record): RepositoryOverviewRow => {
      const origin = recordOrigin(record);
      return {
        kind: "record", key: `record:${record.id}`, id: record.id, name: repositoryDisplayName(record.name), path: record.name,
        origin: origin.label, originTitle: origin.title, access: "–", accessTitle: "Not read through a Knowledge source.",
        status: "–", statusTitle: "", tone: "neutral", canSetUp: false, branch: record.default_branch || null,
        branchFromSource: record.default_branch_from === "knowledge_source", setup: recordSetup(record), recordId: record.id,
      };
    });
  // The records runs use first, then the Knowledge sources.
  return [...ownRecords, ...fromSources];
}
