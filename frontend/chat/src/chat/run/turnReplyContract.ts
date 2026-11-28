// Anything but the closed record reads as no record.

export type TurnReplyContract = {
  status: "satisfied" | "violated";
  reason: string | null;
};

const REASON = /^[a-z][a-z0-9_]{0,63}$/;

export function parseTurnReplyContract(
  value: unknown,
): TurnReplyContract | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const { kind, status, reason } = value as Record<string, unknown>;
  if (kind !== "json_object") return null;
  if (status === "satisfied" && reason === null)
    return { status, reason: null };
  if (
    status === "violated" &&
    typeof reason === "string" &&
    REASON.test(reason)
  ) {
    return { status, reason };
  }
  return null;
}
