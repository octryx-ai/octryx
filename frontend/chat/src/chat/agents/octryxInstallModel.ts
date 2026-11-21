// "Install octryx-claude": reads GET /octryx-claude/version, the platform's public answer with the served
// client version, its sha256 and the copy-paste install one-liners (this platform's URL, optional Workspace).
// Anything unexpected is refused (null) instead of being shown as a command someone might paste.

export type OctryxInstall = {
  version: string;
  sha256: string;
  requiresPython: string;
  macos: string;
  windows: string;
};

const VERSION = /^[0-9][0-9A-Za-z.+_-]{0,63}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MACOS = /^curl -fsSL '(https?:\/\/[^'\s]+\/octryx-claude\/install\.sh(\?workspace=[A-Za-z0-9._:-]+)?)' \| bash$/;
const WINDOWS = /^irm '(https?:\/\/[^'\s]+\/octryx-claude\/install\.ps1(\?workspace=[A-Za-z0-9._:-]+)?)' \| iex$/;

export function readOctryxInstall(payload: unknown): OctryxInstall | null {
  if (!payload || typeof payload !== "object") return null;
  const value = payload as Record<string, unknown>;
  const install = value.install && typeof value.install === "object" ? value.install as Record<string, unknown> : {};
  const { version, sha256 } = value;
  const requiresPython = typeof value.requires_python === "string" ? value.requires_python : "";
  const { macos, windows } = install;
  if (typeof version !== "string" || !VERSION.test(version)) return null;
  if (typeof sha256 !== "string" || !SHA256.test(sha256)) return null;
  if (typeof macos !== "string" || !MACOS.test(macos)) return null;
  if (typeof windows !== "string" || !WINDOWS.test(windows)) return null;
  return { version, sha256, requiresPython, macos, windows };
}

// The same installer with a command: update keeps the login; uninstall --purge also revokes it.
export function macosCommand(install: OctryxInstall, command: "update" | "uninstall"): string {
  const url = (MACOS.exec(install.macos)?.[1] ?? "").replace(/\?workspace=.*$/, "");
  return `curl -fsSL '${url}' | bash -s -- ${command}`;
}

export function windowsCommand(install: OctryxInstall, command: "update" | "uninstall"): string {
  const url = (WINDOWS.exec(install.windows)?.[1] ?? "").replace(/\?workspace=.*$/, "");
  return `& ([scriptblock]::Create((irm '${url}'))) ${command}`;
}

export function installErrorText(error: unknown): string {
  const status = typeof error === "object" && error && "status" in error ? Number((error as { status: unknown }).status) : 0;
  if (status === 404) return "This server does not offer the octryx-claude installer yet.";
  if (status === 503) return "The platform cannot serve the octryx-claude installer: the client package is missing from this installation.";
  if (status === 422) return "This Workspace cannot be preselected in the installer; use the commands without it.";
  return "The install commands could not be loaded. Try again.";
}
