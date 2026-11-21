import { LOGO_BODY_PATH, LOGO_CIRCUIT_PATH } from "./octryxLogoPaths";

/** The Octryx AI logo, drawn in currentColor (the circuit lines lighter). Decorative: the trigger carries the label. */
export function OctryxLogo({ className = "octryx-logo" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 100 100" fill="currentColor" fillRule="evenodd" aria-hidden="true" focusable="false">
      <path d={LOGO_BODY_PATH} />
      <path d={LOGO_CIRCUIT_PATH} opacity={0.62} />
    </svg>
  );
}
