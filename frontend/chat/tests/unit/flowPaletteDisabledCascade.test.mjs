// Judge 24-palette-reason-after: an unavailable palette step must stay `disabled` but render at full
// opacity so its reason is readable. A string check of one file missed that `.flow-builder button:disabled`
// (another file) still won the cascade. This test resolves the cascade the browser applies: every
// opacity rule in the app's CSS is matched against the real element and ancestor chain, and the winner
// is chosen by specificity (it must win outright, so stylesheet order cannot change the result).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../../src/", import.meta.url));

function cssFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return cssFiles(full);
    return entry.name.endsWith(".css") ? [full] : [];
  });
}

// Top-level rules only (rules inside @media/@container are skipped; none set opacity on these buttons).
function opacityRules() {
  const rules = [];
  for (const file of cssFiles(SRC)) {
    const css = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const match of css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)) {
      const value = /(?:^|;)\s*opacity\s*:\s*([^;!]+)(!important)?/.exec(match[2]);
      if (!value) continue;
      for (const selector of match[1].split(",")) {
        rules.push({ file: path.relative(SRC, file), selector: selector.trim(), opacity: Number(value[1]), important: Boolean(value[2]) });
      }
    }
  }
  return rules;
}

// The element: <button class="flow-palette__item flow-palette__item--disabled" disabled> in the editor.
const TARGET = { tag: "button", classes: ["flow-palette__item", "flow-palette__item--disabled"], disabled: true };
const ANCESTORS = [
  ["flow-builder"], ["flow-builder__layout", "flow-builder__layout--editor"], ["flow-builder__main"],
  ["flow-builder__canvas-shell"], ["flow-canvas"], ["flow-palette"], ["flow-palette__groups"],
  ["flow-palette__group"], ["flow-palette__items"],
].map((classes) => ({ tag: "div", classes, disabled: false }));

function parseCompound(text) {
  if (/[[>+~]|::/.test(text)) return null; // attribute/child/sibling selectors: not used by these rules
  const tag = /^[a-z][a-z0-9-]*/i.exec(text)?.[0] ?? null;
  const classes = [...text.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
  const pseudos = [...text.matchAll(/:([\w-]+)(?:\(([^)]*)\))?/g)].map((m) => ({ name: m[1], arg: m[2] }));
  return { tag, classes, pseudos };
}

function compoundMatches(compound, element) {
  if (compound.tag && compound.tag !== element.tag) return false;
  if (!compound.classes.every((name) => element.classes.includes(name))) return false;
  return compound.pseudos.every(({ name, arg }) => {
    if (name === "disabled") return element.disabled;
    if (name === "not") {
      const inner = parseCompound(arg || "");
      return inner ? !compoundMatches(inner, element) : false;
    }
    return false; // :hover, :focus, … are not the resting state
  });
}

function matches(selector) {
  const parts = selector.split(/\s+/).map(parseCompound);
  if (parts.some((part) => part === null)) return false;
  if (!compoundMatches(parts[parts.length - 1], TARGET)) return false;
  let ancestor = ANCESTORS.length - 1;
  for (let index = parts.length - 2; index >= 0; index -= 1) {
    while (ancestor >= 0 && !compoundMatches(parts[index], ANCESTORS[ancestor])) ancestor -= 1;
    if (ancestor < 0) return false;
    ancestor -= 1;
  }
  return true;
}

function specificity(selector) {
  const ids = (selector.match(/#[\w-]+/g) || []).length;
  const notArgs = [...selector.matchAll(/:not\(([^)]*)\)/g)].map((m) => m[1]).join(" ");
  const bare = selector.replace(/:not\(([^)]*)\)/g, "");
  const classes = (bare.match(/\.[\w-]+|:[\w-]+/g) || []).length + (notArgs.match(/\.[\w-]+|:[\w-]+/g) || []).length;
  const tags = (bare.match(/(^|\s)[a-z][a-z0-9-]*/gi) || []).length;
  return ids * 10000 + classes * 100 + tags;
}

test("the disabled palette step resolves to full opacity and keeps its disabled state", () => {
  const applicable = opacityRules().filter((rule) => matches(rule.selector));
  assert.ok(applicable.some((rule) => rule.selector.startsWith(".flow-builder button:disabled")),
    "the shared dimming rule is part of the cascade this test models");
  assert.ok(!applicable.some((rule) => rule.important), "no !important opacity rule may apply");
  const ranked = applicable.map((rule) => ({ ...rule, weight: specificity(rule.selector) }))
    .sort((a, b) => b.weight - a.weight);
  const [winner, runnerUp] = ranked;
  assert.ok(winner.weight > (runnerUp?.weight ?? -1), `ambiguous winner: ${winner.selector} vs ${runnerUp?.selector}`);
  assert.equal(winner.opacity, 1, `${winner.selector} (${winner.file}) decides the opacity`);
  assert.match(winner.selector, /:disabled/, "the override only applies to genuinely disabled buttons");
});

test("an enabled palette step is not affected by the override", () => {
  const enabled = { ...TARGET, disabled: false };
  const override = ".flow-palette button.flow-palette__item--disabled:disabled";
  const compound = parseCompound("button.flow-palette__item--disabled:disabled");
  assert.equal(compoundMatches(compound, enabled), false, override);
});
