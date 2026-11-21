import type { ClipboardEvent } from "react";

import { usePolicyLabel } from "./policyNames";

/** A determining policy: the readable label, the raw id on hover and when the label alone is copied. */
export function PolicyRef({ id, className = "admin-policy-chip" }: { id: string; className?: string }) {
  const label = usePolicyLabel()(id);
  const copyId = (event: ClipboardEvent<HTMLSpanElement>) => {
    if (typeof window === "undefined" || window.getSelection()?.toString().trim() !== label) return;
    event.clipboardData.setData("text/plain", id);
    event.preventDefault();
  };
  return <span className={className} title={id} data-policy-id={id} data-testid="policy-ref" onCopy={copyId}>{label}</span>;
}
