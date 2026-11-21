import { useEffect, useState } from "react";

import { loadWorkspaceClassification } from "../../admin/components/dataClassification/dataClassificationApi";
import { readWorkspaceClassification } from "../../admin/components/dataClassification/dataClassificationModel";
import { seatClassificationRefusal, seatReasonText } from "../../admin/components/dataClassification/dataClassificationSeat";
import { SEAT_CARD_LABEL } from "./agentsFocus";

// Item 3: when the Workspace's classification refuses Claude subscription (seat) sessions, the empty or failed
// connected-clients list says so and links to the Workspace's "Data classification" card. Nothing is shown when the
// classification allows them, or when it cannot be read (the card itself then says why).
export function AgentsSeatRefusal({ projectId, onOpenClassification }: { projectId: string; onOpenClassification: () => void }) {
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setReason(null);
    loadWorkspaceClassification(projectId)
      .then((payload) => {
        if (current) setReason(seatClassificationRefusal(readWorkspaceClassification(payload)));
      })
      .catch(() => undefined);
    return () => { current = false; };
  }, [projectId]);

  if (!reason) return null;
  return (
    <p className="work-area__notice" role="note" data-testid="agents-seat-refused">
      Claude subscription (seat) sessions are refused in this Workspace: {seatReasonText(reason)}.{" "}
      <button type="button" className="admin-panel__action-btn" onClick={onOpenClassification}>Open {SEAT_CARD_LABEL}</button>
    </p>
  );
}
