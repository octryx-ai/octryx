/** Punctuation never becomes an initial: "Acme (demo)" → "AD"; "–" without a usable name. */
export function workspaceInitials(name: string | null | undefined): string {
  const words = String(name ?? "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!words.length) return "–";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function workspaceSwitchLabel(name: string | null | undefined): string {
  return name ? `Workspace: ${name} · change` : "No workspace selected · choose one";
}

export const GLOBAL_WORKSPACE_LABEL = "Global · no workspace";
