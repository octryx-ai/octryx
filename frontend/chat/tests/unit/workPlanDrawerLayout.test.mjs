// Root live acceptance (screenshot 108, 1728x851): the Work Item detail drawer had a 534px client
// width but a 1186px scroll width, because its single implicit grid column and the nested plan grids
// sized to the longest unbroken content (a long question, answer or the Jira approval preview). The
// columns now take the drawer's width and that content wraps; nothing is clipped or hidden. Rendered
// geometry is root's browser check; these are the CSS rules that decide it.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const css = readCssWithImports(new URL("../../src/styles/chat/work-detail.css", import.meta.url))
  .replace(/\r\n/g, "\n")
  .replace(/\/\*[\s\S]*?\*\//g, "");
// Every declaration that applies to exactly this selector, from all rules whose selector list names it.
const rule = (selector) => {
  const bodies = [];
  for (const match of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const selectors = match[1].split(",").map((entry) => entry.trim());
    if (selectors.includes(selector)) bodies.push(match[2]);
  }
  assert.ok(bodies.length, selector);
  return bodies.join("\n");
};

test("the drawer and every plan grid use one column as wide as their container", () => {
  for (const selector of [".work-detail", ".work-detail__section", ".work-change-plan", ".work-change-plan__block",
    ".work-change-plan__delta", ".work-change-plan__decision"]) {
    assert.match(rule(selector), /grid-template-columns: minmax\(0, 1fr\)/, selector);
  }
  assert.match(rule(".work-change-plan__toolbar > div"), /min-width: 0/);
});

test("long questions, answers and the approval preview wrap instead of widening the drawer", () => {
  for (const selector of [".work-change-plan__block li", ".work-change-plan__block p", ".work-change-plan__decision label",
    ".work-change-plan__decision span", ".work-change-plan__delta span", ".work-change-plan__toolbar span"]) {
    assert.match(rule(selector), /overflow-wrap: anywhere/, selector);
  }
  const preview = rule(".work-change-plan__block pre");
  assert.match(preview, /white-space: pre-wrap/);
  assert.match(preview, /overflow-wrap: anywhere/);
});

test("nothing in the plan view is clipped or truncated to fit", () => {
  const planRules = css.split("}").filter((block) => /\.work-change-plan|\.work-detail(\s|\{|__section)/.test(block));
  for (const block of planRules) {
    assert.doesNotMatch(block, /overflow(-x)?:\s*(hidden|clip)|text-overflow|white-space:\s*nowrap/, block.trim());
  }
  assert.match(rule(".work-detail"), /overflow: auto/, "the drawer scrolls vertically");
});

test("the answer form, retained answers and approval preview sit inside these wrapping containers", () => {
  const answers = fs.readFileSync(new URL("../../src/chat/work/WorkPlanClarificationAnswers.tsx", import.meta.url), "utf8");
  assert.match(answers, /className="work-change-plan__decision"/);
  assert.match(answers, /<label htmlFor=\{id\}>/);
  assert.match(answers, /className="work-change-plan__delta" data-testid="clarification-retained"/);
  const plans = ["WorkChangePlans.tsx", "WorkChangePlanView.tsx", "WorkChangePlanBlocks.tsx"]
    .map((file) => fs.readFileSync(new URL(`../../src/chat/work/${file}`, import.meta.url), "utf8")).join("\n");
  assert.match(plans, /<PlanBlock title="Open questions">\s*<WorkPlanClarificationAnswers/);
  assert.match(plans, /<PlanBlock title="Jira approval comment">\s*<pre>/);
  assert.match(plans, /className="work-change-plan__block"/);
});
