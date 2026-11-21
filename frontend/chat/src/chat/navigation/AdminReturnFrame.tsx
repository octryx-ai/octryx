import type { ReactNode } from "react";

import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import type { AdminReturn } from "./adminReturn";
import "./admin-return.css";

// A page Admin opened in another area (Repositories, Jira write-back) with the link back to Admin above it.
export function AdminReturnFrame({ target, onReturn, children }: {
  target: AdminReturn | null; onReturn: (tab: AdminTab) => void; children: ReactNode;
}) {
  if (!target) return <>{children}</>;
  return (
    <div className="admin-return" data-testid="admin-return">
      <nav className="admin-return__bar" aria-label="Back to Admin">
        <button type="button" className="admin-panel__action-btn" onClick={() => onReturn(target.tab)}
          data-testid="admin-return-link">← {target.label}</button>
      </nav>
      {children}
    </div>
  );
}
