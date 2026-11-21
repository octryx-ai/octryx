// Plain text for a turn's state reason. The backend reason text is kept, except for one
// known pair whose wording is internal: `finished_unverified` with `runtime_finished` ("finished; no
// verification contract checked its result"). It means the reply was delivered without passing an
// automated verification step.
// Every other state and reason keeps the backend text, or the state's own description.
const PLAIN_REASONS: Record<string, Record<string, string>> = {
  finished_unverified: {
    runtime_finished: "The reply is ready. It has not passed an automated verification step.",
  },
};

// `state` is the parsed closed state, which may be an unrecognized value; only known pairs match.
export function turnStateReasonText(state: unknown, code: string | null, text: string | null, fallback: string): string {
  const reasons = typeof state === "string" && Object.prototype.hasOwnProperty.call(PLAIN_REASONS, state) ? PLAIN_REASONS[state] : undefined;
  const plain = reasons && code && Object.prototype.hasOwnProperty.call(reasons, code) ? reasons[code] : undefined;
  return plain ?? text ?? fallback;
}
