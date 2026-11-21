import { useState, type ReactNode } from "react";
import { useCanManageWork } from "./workAccess";

import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { useConfirmAction } from "../../admin/components/confirm/useConfirmAction";
import { safeHttpUrl } from "./workItemDetailModel";
import {
  closeRefusalText, closeResultText, closeWhereText, closeWorkItem, isClosedItem, sourceName,
} from "./workItemClose";
import type { WorkItem } from "./workItemTypes";

// The Work Item header's actions: open the item at its source (Jira / ServiceNow), the panel's own actions
// (`children`, e.g. the primary "Start workflow") and the "⋯" menu. Closing the item there or here is in the menu,
// not a button beside ✕.
export function WorkItemHeaderActions({ item, onClosed, children }: { item: WorkItem; onClosed?: () => void; children?: ReactNode }) {
  const confirm = useConfirmAction();
  const canManage = useCanManageWork();
  const [result, setResult] = useState<string | null>(null);
  const url = safeHttpUrl(item.source_url);
  const source = sourceName(item);

  const askClose = () => {
    setResult(null);
    confirm.ask({
      title: `Close ${item.source_key}?`,
      body: <p>{closeWhereText(item)}</p>,
      confirmLabel: `Close ${item.source_key}`,
      tone: "neutral",
      field: { label: "Reason", placeholder: "e.g. Done in the release 4.2", required: false },
      done: "",
      run: async (reason) => {
        try {
          const outcome = await closeWorkItem(item.id, reason);
          setResult(closeResultText(item, outcome));
          onClosed?.();
        } catch (failure) {
          throw new Error(closeRefusalText(failure));
        }
      },
    });
  };

  return (
    <div className="work-detail__header-actions" data-testid="work-item-header-actions">
      {url ? (
        <a className="admin-panel__action-btn" href={url} target="_blank" rel="noopener noreferrer"
          data-testid="work-item-source-link">Open in {source}</a>
      ) : null}
      {children}
      {isClosedItem(item) || !canManage ? null : (
        <ActionMenu row={{ objectName: item.source_key }}
          items={[{ label: "Close item", onSelect: askClose, testId: "work-item-close" }]} />
      )}
      {result ? <p className="work-detail__result" role="status" data-testid="work-item-close-result">{result}</p> : null}
      {confirm.dialog}
    </div>
  );
}
