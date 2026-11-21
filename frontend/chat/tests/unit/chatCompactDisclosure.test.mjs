// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Accessible-control contract for the narrow-viewport chat workspace.
// The harness cannot load `.tsx` (Node type stripping does not transform JSX),
// so the components are asserted from source the same way
// `turnExecutionSummaryContract.test.mjs` asserts the backend builder.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

function source(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8").replace(
    /\r\n/g,
    "\n",
  );
}

const COMPOSER_FOOTER = source(
  "../../src/chat/ComposerFooterControls.tsx",
);
const HEADER_ACTIONS = source(
  "../../src/chat/header/WorkspaceHeaderActions.tsx",
);
const HEADER_MENU = source(
  "../../src/chat/header/WorkspaceHeaderOverflowMenu.tsx",
);

test("the compact composer disclosure is labelled and wired to its panel", () => {
  const panelId = /const COMPACT_OPTIONS_PANEL_ID = "([^"]+)"/.exec(
    COMPOSER_FOOTER,
  );
  assert.ok(panelId, "compact options panel id is not declared");

  assert.match(COMPOSER_FOOTER, /aria-expanded=\{compactOptionsOpen\}/);
  assert.match(
    COMPOSER_FOOTER,
    /aria-controls=\{COMPACT_OPTIONS_PANEL_ID\}/,
    "the disclosure trigger does not point at the panel it opens",
  );
  assert.match(
    COMPOSER_FOOTER,
    /id=\{COMPACT_OPTIONS_PANEL_ID\}/,
    "the disclosed panel does not carry the referenced id",
  );
  // A visible text label, not an icon-only control.
  assert.match(COMPOSER_FOOTER, /<span>Options<\/span>/);
});

test("message entry, attach and send stay outside the composer disclosure", () => {
  const compactBranch = COMPOSER_FOOTER.slice(
    COMPOSER_FOOTER.indexOf("if (compactComposer) {"),
    COMPOSER_FOOTER.indexOf("  return (\n    <div className=\"composer__footer\">"),
  );
  assert.ok(compactBranch.length > 0, "compact composer branch not found");

  const disclosedPanel = compactBranch.slice(
    compactBranch.indexOf("{compactOptionsOpen ? ("),
  );
  assert.match(compactBranch, /<ComposerAttachButton/);
  assert.match(compactBranch, /\{submitButton\}/);
  assert.doesNotMatch(
    disclosedPanel,
    /<ComposerAttachButton|\{submitButton\}/,
    "attach or send/stop were moved behind the disclosure",
  );
  // Routing and utility controls are the collapsed ones.
  assert.match(disclosedPanel, /\{routingPills\}/);
  assert.match(disclosedPanel, /\{utilityActions\(false\)\}/);
});

test("execution state stays reachable without opening the header menu", () => {
  const phoneBranch = HEADER_ACTIONS.slice(
    HEADER_ACTIONS.indexOf('if (layoutMode === "phone") {'),
    HEADER_ACTIONS.indexOf('  return (\n    <div className="workspace__actions">'),
  );
  assert.ok(phoneBranch.length > 0, "phone header branch not found");

  const overflowItems = phoneBranch.slice(
    phoneBranch.indexOf("const overflowItems"),
    phoneBranch.indexOf("return ("),
  );
  assert.doesNotMatch(
    overflowItems,
    /traceAction|errorAction/,
    "trace or action-error was collapsed into the overflow menu",
  );
  assert.match(phoneBranch, /\{errorAction\}\n\s*\{traceAction\(false\)\}/);

  assert.match(HEADER_MENU, /aria-haspopup="menu"/);
  assert.match(HEADER_MENU, /aria-expanded=\{open\}/);
  assert.match(HEADER_MENU, /aria-label=\{trigger\?\.ariaLabel \?\? "More chat actions"\}/);
  assert.match(HEADER_MENU, /role="menuitem"/);
});
