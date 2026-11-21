// Render guards for run and device cards (decision card, device run policy): key text and structure stay the same
// when the cards are split into smaller parts. Data hooks and heavy children are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, load, noop, render, text } from "./renderGuardHarness.mjs";

const json = (value) => JSON.stringify(value);
const classes = (root, name) => root.findAll((node) => typeof node.props?.className === "string"
  && node.props.className.split(" ").includes(name) && typeof node.type === "string");

test("the decision card shows findings, screenshots, tasks, questions, the note and the verdict buttons", async () => {
  const run = { id: "r1", updated_at: "u", branch: "feat/x", gate: { state: "passed" }, task_list: [{ id: "1", text: "T" }],
    actions: [{ key: "confirm", label: "Ship" }, { key: "change", label: "Change" }] };
  const card = { subject: "decisions", verdict: "changes", heading: "Review", summary: "Sum", note: "The note",
    findings: [{ severity: "high", fix: "Fix it", file: "a.ts", line: 3 }], questions: ["Is it ok?", "Really?"] };
  const screens = { screens: Array.from({ length: 6 }, (_, i) => ({ name: `s${i}.png` })) };
  const chosen = [];
  const { DecisionCard } = load("chat/workflowRun/DecisionCard.tsx", {
    useRunResource: { useRunResource: (path) => (path ? screens : null) },
    TaskList: { TaskList: box("tasks") },
    StatusLabel: { StatusLabel: (p) => createElement("span", { "data-testid": "status" }, p.label) },
    MarkdownRenderer: { MarkdownRenderer: (p) => createElement("div", { "data-testid": "markdown" }, p.content) },
  }, { document: { documentElement: { getAttribute: () => "dark" } } });
  const view = await render(DecisionCard, { run, card, events: [], busy: false, onChoose: (action, value) => chosen.push([action.key, value ?? null]) });
  const root = view.root;
  assert.equal(text(root.findByProps({ className: "decision-card__title" })), "Review");
  assert.equal(json(root.findAllByProps({ "data-testid": "status" }).map((node) => text(node))), json(["Not ready to ship", "high"]));
  assert.equal(text(root.findByProps({ className: "decision-card__facts" })), "Checks passedBranch feat/x");
  assert.equal(root.findAllByType("img").length, 4);
  assert.equal(root.findAllByProps({ "data-testid": "tasks" }).length, 1);
  assert.equal(root.findAllByType("input").length, 2);
  assert.equal(root.findAllByType("textarea").length, 2);
  assert.equal(text(root.findByProps({ "data-testid": "markdown" })), "The note");
  const foot = root.findByProps({ className: "decision-card__foot" }).findAllByType("button");
  assert.equal(json(foot.map((button) => button.props["data-testid"])), json(["decision-card-confirm", "decision-card-change"]));
  act(() => root.findAllByType("input")[0].props.onChange({ target: { value: "Yes" } }));
  assert.equal(text(root.findByProps({ className: "decision-card__hint" })), "1 of 2 answered");
  act(() => root.findByProps({ className: "decision-card__link" }).props.onClick());
  assert.equal(root.findAllByType("img").length, 6);
  act(() => root.findByProps({ "data-testid": "decision-card-change" }).props.onClick());
  assert.equal(chosen[0][0], "change");
  assert.match(chosen[0][1], /Yes/);
  act(() => view.unmount());
});
