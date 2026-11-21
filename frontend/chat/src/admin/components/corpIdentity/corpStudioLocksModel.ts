// Pure rules of the Corporate Identity's Spec Studio settings: the lockable values and the Workspace
// select's company default. Kept apart from the components so the unit tests load them.

const THEME_KEYS = ["bg", "surface", "text", "muted", "accent", "ok", "warn", "error"] as const;
const NAMES: Record<string, string> = {
  bg: "Background", surface: "Cards", text: "Text", muted: "Muted text", accent: "Main action", ok: "OK",
  warn: "Warning", error: "Error",
};

export const LOCK_GROUPS: { title: string; paths: { path: string; label: string }[] }[] = [
  { title: "Light colours", paths: THEME_KEYS.map((key) => ({ path: `light.${key}`, label: NAMES[key] })) },
  { title: "Dark colours", paths: THEME_KEYS.map((key) => ({ path: `dark.${key}`, label: NAMES[key] })) },
  { title: "Type and shape", paths: [{ path: "fonts.head", label: "Heading font" }, { path: "fonts.body", label: "Text font" },
    { path: "radius", label: "Corners" }, { path: "logo", label: "Logo" }, { path: "icons", label: "Icons" }] },
];

/** A token path as people read it: "Main action (light)", "Heading font", "Style direction"; unknown: the path. */
export function lockLabel(path: string): string {
  if (path === "direction") return "Style direction";
  const [theme, key] = path.split(".");
  if ((theme === "light" || theme === "dark") && key && NAMES[key]) return `${NAMES[key]} (${theme})`;
  return LOCK_GROUPS.flatMap((group) => group.paths).find((item) => item.path === path)?.label ?? path;
}

/** An open point about a deviation ("deviation:<path>"), in words: what differs and that a reason is asked for. */
export function deviationPointText(target: string, fallback: string): string {
  return target.startsWith("deviation:")
    ? `${lockLabel(target.slice("deviation:".length))} differs from Corporate: give the reason.`
    : fallback;
}

/** The locks after toggling one path: sorted, without duplicates (what the server stores). Pure. */
export function toggleLock(locks: string[], path: string, on: boolean): string[] {
  const next = new Set(locks);
  if (on) next.add(path); else next.delete(path);
  return [...next].sort();
}

export type Profile = { id: string; name: string; is_default?: boolean };

/** The select's label for the company default: "Company default (<name>)" or "Company default (none yet)". */
export function companyDefaultLabel(profiles: Profile[]): string {
  const fallback = profiles.find((profile) => profile.is_default);
  return `Company default (${fallback ? fallback.name : "none yet"})`;
}
