import type { WorkItemSelection } from "./useWorkItemSelection";
import { SidePanel } from "../../layout/SidePanel";

// Shown while a selected Work Item that is not in the loaded list is read by id, or when that read
// fails (for example 404 or no workspace access). It never shows a plan summary as the Work Item.
export function WorkItemDetailPending({ selection, onClose }: { selection: WorkItemSelection; onClose: () => void }) {
  return (
    <SidePanel title="Work item" onClose={onClose} testId="work-item-panel">
      <div className="work-detail" aria-label="Work Item detail" data-testid="work-item-detail">
        <p role={selection.error ? "alert" : "status"}>
          {selection.error ? `The Work Item could not be opened: ${selection.error}` : "Loading the Work Item…"}
        </p>
      </div>
    </SidePanel>
  );
}
