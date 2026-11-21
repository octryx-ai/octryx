import type { ReactNode } from "react";

// A form field with its visible label (no field is labelled by its placeholder alone).
export function KnowledgeFormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="admin-panel__field">
      <span>{label}</span>
      {children}
    </label>
  );
}
