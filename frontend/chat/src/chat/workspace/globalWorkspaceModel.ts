// Pure helpers of the one global Workspace switch.

/**
 * Up to two letters or digits for the rail button: "Acme" → "AC", "ux first run" → "UF",
 * "Acme (demo)" → "AD"; punctuation never becomes an initial. "–" without a usable name.
 */
export function workspaceInitials(name: string | null | undefined): string {
  const words = String(name ?? "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!words.length) return "–";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** The accessible name and tooltip of the switch. */
export function workspaceSwitchLabel(name: string | null | undefined): string {
  return name ? `Workspace: ${name} · change` : "No workspace selected · choose one";
}

/** The administrators' choice to chat without a Workspace (the chat's "Global"). */
export const GLOBAL_WORKSPACE_LABEL = "Global · no workspace";
