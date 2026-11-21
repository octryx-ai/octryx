// Status badge class of a flow in the builder's header (draft, published, other).
export function flowStatusClass(value: string): string {
  if (value === "published") return "flow-builder__badge--ok";
  if (value === "draft") return "flow-builder__badge--draft";
  return "flow-builder__badge--neutral";
}
