import assert from "node:assert/strict";
import { test } from "node:test";

import { CHAT_ROOT, commentStyleCounts, fileCounts, sourceFiles, strictProblems } from "./commentStyleScan.mjs";

const code = (lines) => "const value = 1;\n".repeat(lines);
const FILLER = code(6);

test("every frontend file follows the comment style (no baseline)", () => {
  const problems = strictProblems(commentStyleCounts(CHAT_ROOT, sourceFiles()));
  assert.deepEqual(problems, [], `${problems.length} comment style problem(s):\n  ${problems.join("\n  ")}`);
});

for (const [name, relative, source, expected] of [
  ["a JSDoc block over 2 lines", "src/planted.ts", "/**\n * One.\n * Two.\n */\n" + FILLER.repeat(4), [2, 0, 0, 0]],
  ["narration in a line comment", "src/planted.ts", "const a = 1; // moved from old.ts\n" + FILLER, [0, 1, 0, 0]],
  ["narration in a directive", "src/planted.ts", "// eslint-disable-next-line no-console -- moved from old.ts\n" + FILLER,
    [0, 1, 0, 0]],
  ["narration in a JSX comment", "src/planted.tsx", "export const A = () => <div>{/* C12B-04 */}</div>;\n" + FILLER,
    [0, 1, 0, 0]],
  ["a comment share over 15 %", "src/planted.ts", "// why\n// and why\n" + FILLER, [0, 0, 2, 8]],
  ["a JSDoc share over 15 %", "src/planted.ts", "/** One.\n * Two. */\nexport const a = 1;\n", [0, 0, 2, 3]],
]) {
  test(`mutation: ${name} in a new file is reported`, () => {
    const counts = fileCounts(relative, source);
    assert.deepEqual(counts, expected);
    assert.notDeepEqual(strictProblems({ [relative]: counts }), []);
  });
}

for (const [name, source] of [
  ["a two-line JSDoc block", "/** One.\n * Two. */\n" + code(12)],
  ["comment-like text in strings and JSX", "const url = 'http://x//y';\nconst a = <a>// C12-01</a>;\n" + FILLER],
  ["one comment line in a tiny file", "// why\nexport const a = 1;\n"],
  ["tool directives", "// eslint-disable-next-line no-console\n// @ts-expect-error: untyped\n" + FILLER],
]) {
  test(`mutation: ${name} passes`, () => {
    assert.deepEqual(fileCounts("src/planted.tsx", source), [0, 0, 0, 0]);
  });
}

const PLANTED = "src/planted.ts";

test("mutation: each rule is a failure with its count, whatever the file was before", () => {
  const counts = fileCounts(PLANTED, "/**\n * One.\n * Two.\n */\nconst a = 1; // finding C12-01\n// why\n" + code(2));
  assert.deepEqual(strictProblems({ [PLANTED]: counts }), [
    `${PLANTED}: JSDoc lines beyond 2 2: fix them`,
    `${PLANTED}: narration lines 1: fix them`,
    `${PLANTED}: comment lines over 15 % ${counts[2]}/${counts[3]}: remove comments`,
  ]);
});
