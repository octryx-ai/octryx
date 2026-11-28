import type { HandoffSections } from "./agentHandoffTypes";

// Only a plain branch name goes into a copy-able command, so a crafted handoff can never inject shell syntax.

const BRANCH = /^(?!-)(?!.*\.\.)(?!.*\/\/)(?!.*@\{)(?!.*\.lock$)(?!.*\/$)(?!.*\.$)[A-Za-z0-9._/-]{1,200}$/;
const COMMIT = /^[0-9a-f]{7,64}$/;

export function isSafeBranch(name: string): boolean {
  return BRANCH.test(name);
}

export function isCommitId(value: string): boolean {
  return COMMIT.test(value);
}

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

export function excludedWarning(files: string[]): string {
  if (!files.length) return "";
  return `${files.length} ${files.length === 1 ? "file was" : "files were"} not handed over because ${files.length === 1 ? "it looks" : "they look"} secret-bearing or ignored: ${files.join(", ")}. Recreate ${files.length === 1 ? "it" : "them"} locally if needed.`;
}
