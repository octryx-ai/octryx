// Spec Studio icons: clean line icons in the Octryx style (24 px grid, 1.75 px stroke, round caps, currentColor),
// never emoji (the owner rejected a speech-bubble emoji). The mock icons (bean, cup, grinder …) draw the
// product's own screens; the tool icons (comment, zoom, desktop, phone …) the Studio's controls.

import { PATHS, type StudioIconName } from "./specStudioIconPaths";

/** One line icon; decorative (the button or label around it carries the name). */
export function StudioIcon({ name, size = 16, className = "" }: { name: StudioIconName; size?: number; className?: string }) {
  return (
    <svg className={`studio-icon${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={name === "more" ? 2.75 : 1.75} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
