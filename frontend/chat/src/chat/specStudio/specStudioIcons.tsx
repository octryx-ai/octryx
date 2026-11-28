import { PATHS, type StudioIconName } from "./specStudioIconPaths";

export function StudioIcon({ name, size = 16, className = "" }: { name: StudioIconName; size?: number; className?: string }) {
  return (
    <svg className={`studio-icon${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={name === "more" ? 2.75 : 1.75} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
