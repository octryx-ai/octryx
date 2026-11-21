import type { ReactNode } from "react";
import "./flowInspectorPanel.css";

// The selected step's settings beside the workflow graph. It takes real layout space, so the
// graph is never covered; Close (or Escape inside the panel) clears the selection and the graph refits.
export function FlowInspectorPanel({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <aside
      className="flow-builder__inspector"
      aria-label="Step settings"
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="flow-builder__inspector-bar">
        <span>Step settings</span>
        <button type="button" onClick={onClose} aria-label="Close step settings">
          Close
        </button>
      </div>
      {children}
    </aside>
  );
}
