import { useState } from "react";
import type { ReactNode } from "react";
import { useKnowledgePermissionState } from "../../knowledge/useKnowledgePermissions";
import { addRepositoryFromConnectionHref } from "../../../admin/components/workspaceKnowledge/sourceLinks";
import { RepositoryOverview, RepositoryPage } from "./RepositoryPage";
import { AddRunRepositoryPanel } from "./AddRunRepositoryPanel";
import { useWorkspaceRepositoryList } from "./useWorkspaceRepositoryList";
import { workspaceRepositoryRows } from "./workspaceRepositoryRows";
import { LoadingState } from "../../../layout/LoadingState";
import "./repositories.css";

// Work › Repositories: the Workspace's repository records and its Knowledge git sources. `embedded`: the body of the
// Work page (its header and menu are the Work area's); otherwise a page of its own with the same header.
export function RepositoryList({ workspaceId, workspaceControl, embedded = false, onOpenRepositorySettings }: {
  workspaceId: string; workspaceControl: ReactNode; embedded?: boolean;
  // Admin › Workspace › Repositories, where a repository's coding setup is edited (Workspace owners and admins).
  onOpenRepositorySettings?: () => void;
}) {
  const permission = useKnowledgePermissionState(workspaceId);
  const mayAuthor = permission.mayAuthor;
  const list = useWorkspaceRepositoryList(workspaceId, mayAuthor);
  // "Add a repository for runs" (alpha): its side panel; a Workspace owner or admin adds one.
  const [addingForRuns, setAddingForRuns] = useState(false);
  // The list (and its empty state) only once every read it lists is in: the records, whether this person may author,
  // and for an author the Knowledge sources.
  const listed = list.recordsListed && permission.resolved && (!mayAuthor || list.sourcesListed);

  const body = <>
    {list.error ? <p role="alert" className="repository-list__error">{list.error}</p> : null}
    {!listed ? <LoadingState label="repositories" /> : <RepositoryOverview
      rows={workspaceRepositoryRows(list.records, list.sources)} mayAuthor={mayAuthor}
      onEditSetup={mayAuthor ? onOpenRepositorySettings : undefined}
      busy={list.busy} addSourceHref={addRepositoryFromConnectionHref(workspaceId)}
      onAddForRuns={mayAuthor ? () => setAddingForRuns(true) : undefined}
      onConnect={(id) => void list.bind(id)} />}
    {addingForRuns ? <AddRunRepositoryPanel workspaceId={workspaceId} knowledgeHref={addRepositoryFromConnectionHref(workspaceId)}
      onClose={() => setAddingForRuns(false)}
      onAdded={() => { setAddingForRuns(false); void list.refreshRecords().catch(() => {}); }} /> : null}
  </>;

  if (embedded) {
    return <div className="repository-list repository-list--embedded" aria-label="Repositories" aria-busy={list.busy}>
      {body}
    </div>;
  }
  return <RepositoryPage busy={list.busy} controls={workspaceControl}>{body}</RepositoryPage>;
}
