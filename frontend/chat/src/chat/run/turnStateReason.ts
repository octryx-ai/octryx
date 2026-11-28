// `finished_unverified` with `runtime_finished` has internal wording: the reply was delivered without automated verification.
const PLAIN_REASONS: Record<string, Record<string, string>> = {
  finished_unverified: {
    runtime_finished: "The reply is ready. It has not passed an automated verification step.",
  },
};

export function turnStateReasonText(state: unknown, code: string | null, text: string | null, fallback: string): string {
  const reasons = typeof state === "string" && Object.prototype.hasOwnProperty.call(PLAIN_REASONS, state) ? PLAIN_REASONS[state] : undefined;
  const plain = reasons && code && Object.prototype.hasOwnProperty.call(reasons, code) ? reasons[code] : undefined;
  return plain ?? text ?? fallback;
}
