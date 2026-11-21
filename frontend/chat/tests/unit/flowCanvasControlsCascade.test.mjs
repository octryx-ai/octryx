// Live judge (screenshot 23): React Flow's zoom controls rendered empty because the shared
// `.flow-builder button` rule won the cascade (padding 6px 12px in a 26px border-box button, icons
// 0×0), and the "Run & results" dock toggle covered the lower controls. This resolves the cascade
// for the real element chain across the app's CSS and React Flow's own stylesheet; the winning rule
// must win outright by specificity, so stylesheet order cannot change the result.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../../src/", import.meta.url));
const XYFLOW_CSS = fileURLToPath(new URL("../../node_modules/@xyflow/react/dist/style.css", import.meta.url));

function cssFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return cssFiles(full);
    return entry.name.endsWith(".css") ? [full] : [];
  });
}

const STYLESHEETS = [...cssFiles(SRC), XYFLOW_CSS].map((file) => ({
  file: path.basename(file),
  css: fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/@import[^;]*;/g, ""),
}));

function declarations(property) {
  const rules = [];
  const pattern = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;!]+)(!important)?`);
  for (const { file, css } of STYLESHEETS) {
    for (const match of css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)) {
      const value = pattern.exec(match[2]);
      if (!value) continue;
      for (const selector of match[1].split(",")) rules.push({ file, selector: selector.trim(), value: value[1].trim(), important: Boolean(value[2]) });
    }
  }
  return rules;
}

const el = (tag, ...classes) => ({ tag, classes });
// The editor's element chain down to React Flow's bottom-left controls panel.
const PANEL = el("div", "react-flow__panel", "react-flow__controls", "bottom", "left");
const CHAIN = [
  el("div", "flow-builder"), el("div", "flow-builder__layout", "flow-builder__layout--editor"), el("div", "flow-builder__main"),
  el("div", "flow-builder__canvas-shell"), el("div", "flow-canvas"), el("div", "flow-canvas__graph"), el("div", "react-flow"),
];
const BUTTON = el("button", "react-flow__controls-button", "react-flow__controls-zoomin");
const ICON = el("svg");

function parseCompound(text) {
  if (/[[>+~]|::/.test(text)) return null;
  return {
    tag: /^[a-z][a-z0-9-]*/i.exec(text)?.[0] ?? null,
    classes: [...text.matchAll(/\.([\w-]+)/g)].map((m) => m[1]),
    pseudos: [...text.matchAll(/:([\w-]+)/g)].map((m) => m[1]),
  };
}

// Resting state: rules with :hover/:focus/:disabled/:last-child do not apply to the first button.
function compoundMatches(compound, element) {
  if (compound.tag && compound.tag !== element.tag) return false;
  if (!compound.classes.every((name) => element.classes.includes(name))) return false;
  return compound.pseudos.length === 0;
}

function matches(selector, target, ancestors) {
  const parts = selector.split(/\s+/).map(parseCompound);
  if (parts.some((part) => part === null)) return false;
  if (!compoundMatches(parts.at(-1), target)) return false;
  let ancestor = ancestors.length - 1;
  for (let index = parts.length - 2; index >= 0; index -= 1) {
    while (ancestor >= 0 && !compoundMatches(parts[index], ancestors[ancestor])) ancestor -= 1;
    if (ancestor < 0) return false;
    ancestor -= 1;
  }
  return true;
}

function specificity(selector) {
  const classes = (selector.match(/\.[\w-]+|:[\w-]+/g) || []).length;
  const tags = (selector.match(/(^|\s)[a-z][a-z0-9-]*/gi) || []).length;
  return classes * 100 + tags;
}

function winner(property, target, ancestors) {
  const applicable = declarations(property).filter((rule) => matches(rule.selector, target, ancestors));
  assert.ok(!applicable.some((rule) => rule.important), `no !important ${property} applies`);
  const ranked = applicable.map((rule) => ({ ...rule, weight: specificity(rule.selector) })).sort((a, b) => b.weight - a.weight);
  assert.ok(ranked.length, `some rule sets ${property}`);
  assert.ok(ranked[0].weight > (ranked[1]?.weight ?? -1), `ambiguous ${property}: ${ranked[0].selector} vs ${ranked[1]?.selector}`);
  return { ranked, top: ranked[0] };
}

test("the zoom control buttons get React Flow's geometry back, not the shared button padding", () => {
  const ancestors = [...CHAIN, PANEL];
  const padding = winner("padding", BUTTON, ancestors);
  assert.ok(padding.ranked.some((rule) => rule.selector === ".flow-builder button"), "the shared rule is part of the modelled cascade");
  assert.equal(padding.top.value, "4px", `${padding.top.selector} (${padding.top.file})`);
  assert.equal(winner("border-radius", BUTTON, ancestors).top.value, "0");
  // 26px border-box minus 2 × 4px padding leaves 18px, enough for the 12px icon.
  assert.equal(winner("width", BUTTON, ancestors).top.value, "26px");
});

test("the control icons have an explicit 12px size and do not shrink", () => {
  const ancestors = [...CHAIN, PANEL, BUTTON];
  assert.equal(winner("width", ICON, ancestors).top.value, "12px");
  assert.equal(winner("height", ICON, ancestors).top.value, "12px");
  assert.equal(winner("flex", ICON, ancestors).top.value, "none");
});

test("the controls stack starts above the Run & results dock toggle", () => {
  const margin = winner("margin-bottom", PANEL, CHAIN).top;
  const reserved = [...margin.value.matchAll(/(\d+(?:\.\d+)?)px/g)].reduce((sum, m) => sum + Number(m[1]), 0);
  const dock = STYLESHEETS.find(({ file }) => file === "flowBuilderPanelSections.css").css;
  const rule = dock.slice(dock.indexOf(".flow-builder__dock-toggle {"), dock.indexOf("}", dock.indexOf(".flow-builder__dock-toggle {")));
  const px = (name) => Number(new RegExp(`${name}:\\s*(\\d+)px`).exec(rule)?.[1]);
  const dockTop = px("bottom") + px("min-height");
  assert.ok(reserved >= dockTop + 8, `controls start ${reserved}px above the graph bottom; the dock toggle reaches ${dockTop}px`);
});
