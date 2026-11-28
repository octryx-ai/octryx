import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { parse } = require("@typescript-eslint/typescript-estree");

export const CHAT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const RULES = ["JSDoc lines beyond 2", "narration lines", "comment lines over 15 %"];
const SOURCE = /\.(ts|tsx|js|jsx|mjs)$/;
const MAX_JSDOC_LINES = 2;
const MAX_COMMENT_SHARE = 0.15;
const FREE_COMMENT_LINES = 1;
const SHARE = RULES.length - 1;
const NARRATION = new RegExp([
  String.raw`\bC\d+[A-Z]?-\d+\b`,
  String.raw`\bobservability O-?D?\d+\b|\bO-D\d+\b`,
  String.raw`\b[BSH]-0\d\b`,
  String.raw`\bCut \d+\b`,
  String.raw`\(owner \d{1,2}\.\d{1,2}|\bowner decision (of )?\d`,
  String.raw`\btrain \d+\b`,
  String.raw`\bcodex audit|\baudit finding|\bfinding [A-Z]-?\d|\bticket [A-Z]+-\d+`,
  String.raw`\bmoved from\b|\bformerly\b|\bfor backward|\bbackwards? compat`,
].join("|"), "i");
const TOOL_DIRECTIVE = /^\s*(eslint-|@ts-|prettier-ignore|@vite-ignore|c8 |istanbul |\/ <reference)/;

export function sourceFiles(root = CHAT_ROOT) {
  return fs.readdirSync(path.join(root, "src"), { recursive: true })
    .filter((name) => SOURCE.test(name))
    .map((name) => path.posix.join("src", name.split(path.sep).join("/")))
    .sort();
}

export function fileCounts(relative, source) {
  const { comments } = parse(source, { comment: true, jsx: relative.endsWith("x"), loc: true });
  const lines = source.split("\n");
  let jsdocExcess = 0;
  const narrated = new Set();
  const commentLines = new Set();
  for (const comment of comments) {
    const { start, end } = comment.loc;
    comment.value.split("\n").forEach((text, offset) => {
      if (NARRATION.test(text)) narrated.add(start.line + offset);
    });
    if (comment.type === "Block" && comment.value.startsWith("*")) {
      jsdocExcess += Math.max(0, end.line - start.line + 1 - MAX_JSDOC_LINES);
    }
    if (!TOOL_DIRECTIVE.test(comment.value)) {
      for (let line = start.line; line <= end.line; line += 1) commentLines.add(line);
    }
  }
  const nonBlank = lines.filter((line) => line.trim()).length;
  const overShare = commentLines.size > Math.max(FREE_COMMENT_LINES, MAX_COMMENT_SHARE * nonBlank);
  return [jsdocExcess, narrated.size, ...(overShare ? [commentLines.size, nonBlank] : [0, 0])];
}

export function commentStyleCounts(root, files) {
  const found = {};
  for (const relative of files) {
    const counts = fileCounts(relative, fs.readFileSync(path.join(root, relative), "utf8"));
    if (counts.some(Boolean)) found[relative] = counts;
  }
  return found;
}

// No baseline: every file of the frontend follows the rules, so any finding is a failure, never a new row.
export function strictProblems(found) {
  const problems = [];
  for (const key of Object.keys(found).sort()) {
    const counts = found[key];
    RULES.slice(0, SHARE).forEach((rule, index) => {
      if (counts[index]) problems.push(`${key}: ${rule} ${counts[index]}: fix them`);
    });
    if (counts[SHARE]) problems.push(`${key}: ${RULES[SHARE]} ${counts[SHARE]}/${counts[SHARE + 1]}: remove comments`);
  }
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const problems = strictProblems(commentStyleCounts(CHAT_ROOT, sourceFiles()));
  for (const problem of problems) console.error(problem);
  process.exitCode = problems.length ? 1 : 0;
}
