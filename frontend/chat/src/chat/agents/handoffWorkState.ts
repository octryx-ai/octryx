import type { HandoffSections } from "./agentHandoffTypes";

// The work state of a handoff (root freeze 3c): the WIP branch on the Workspace's remote, or a git bundle on
// Octryx when the branch could not be pushed. Pure: no requests, no React.
//
// A copy-able command is built only from a branch name that is a plain git branch name, so a crafted value in a
// handoff can never put shell syntax into the command a person pastes into a terminal.

const BRANCH = /^(?!-)(?!.*\.\.)(?!.*\/\/)(?!.*@\{)(?!.*\.lock$)(?!.*\/$)(?!.*\.$)[A-Za-z0-9._/-]{1,200}$/;
const COMMIT = /^[0-9a-f]{7,64}$/;

/** Whether the branch name is safe to put into a shell command: letters, digits, `._/-`, no git-reserved shapes. */
export function isSafeBranch(name: string): boolean {
  return BRANCH.test(name);
}

/** A commit id as sent (hex, 7–64); anything else is shown as text but never used. */
export function isCommitId(value: string): boolean {
  return COMMIT.test(value);
}

/** `git fetch origin <branch> && git checkout <branch>` for a safe branch, else "" (nothing to copy). */
export function checkoutCommand(branch: string): string {
  return isSafeBranch(branch) ? `git fetch origin ${branch} && git checkout ${branch}` : "";
}

export type WorkState = {
  branch: string;
  command: string;
  bundleId: string;
  baseCommit: string;
  wipCommit: string;
  excludedFiles: string[];
};

/** The work-state block of a handoff, or null when it carries none (an S4 handoff without repo facts). */
export function workState(sections: HandoffSections): WorkState | null {
  const repo = sections.repo;
  const excluded = sections.excludedFiles;
  if (!repo?.branch && !repo?.bundleId && !repo?.wipCommit && !excluded.length) return null;
  return {
    branch: repo?.branch ?? "",
    command: repo?.branch ? checkoutCommand(repo.branch) : "",
    bundleId: repo?.bundleId ?? "",
    baseCommit: repo?.baseCommit ?? "",
    wipCommit: repo?.wipCommit ?? "",
    excludedFiles: excluded,
  };
}

/** The warning for files that stayed on the machine (names only; the server never has their content). */
export function excludedWarning(files: string[]): string {
  if (!files.length) return "";
  return `${files.length} ${files.length === 1 ? "file was" : "files were"} not handed over because ${files.length === 1 ? "it looks" : "they look"} secret-bearing or ignored: ${files.join(", ")}. Recreate ${files.length === 1 ? "it" : "them"} locally if needed.`;
}
