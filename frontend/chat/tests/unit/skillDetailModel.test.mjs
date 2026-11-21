import assert from "node:assert/strict";
import { test } from "node:test";
import {
  checkSentence, findingPlace, findingsBySeverity, ownerName, parseTags, pluginLayout, reachSummary, sameIds, toggleId, workingVersion,
} from "../../src/admin/components/skillCatalog/skillDetailModel.ts";

test("the page works on the open version, else the published one", () => {
  const published = { version: 2 }, open = { version: 3 }, retired = { version: 1 };
  assert.equal(workingVersion({ open, published, versions: [open, published] }), open);
  assert.equal(workingVersion({ open: null, published, versions: [published] }), published);
  assert.equal(workingVersion({ open: null, published: null, versions: [retired] }), retired);
  assert.equal(ownerName({ owner_id: "u1", versions: [{ created_by: "u1", author_name: "Casey" }] }), "Casey");
  assert.equal(ownerName({ owner_id: null, versions: [] }), "—");
});

test("findings group by severity in high → medium → info order and keep their place", () => {
  const finding = (id, severity, file = null, line = null) => ({ id, severity, file, line });
  const groups = findingsBySeverity([finding("a", "info"), finding("b", "high", "scripts/x.sh", 3), finding("c", "info")]);
  assert.deepEqual(groups.map((group) => [group.severity, group.findings.map((item) => item.id)]), [["high", ["b"]], ["info", ["a", "c"]]]);
  assert.equal(findingPlace(groups[0].findings[0]), "scripts/x.sh:3");
  assert.equal(findingPlace({ file: "SKILL.md", line: null }), "SKILL.md");
  assert.deepEqual(toggleId(["a"], "b", true), ["a", "b"]);
  assert.deepEqual(toggleId(["a", "b"], "a", false), ["b"]);
  assert.equal(sameIds(["a", "b"], ["b", "a"]), true);
});

test("tags, upstream check sentences and the delivered layout", () => {
  assert.deepEqual(parseTags(" #terraform, helm  helm,,read-only "), ["terraform", "helm", "read-only"]);
  const update = checkSentence({ update_available: true, current_commit: "0374056f0000", latest_commit: "4451ceca0000", path_moved: { from: "a", to: "b" } });
  assert.equal(update.tone, "update");
  assert.match(update.text, /0374056f → 4451ceca, skill folder moved/);
  assert.equal(checkSentence({ update_available: false, compare_ref: "main", latest_commit: "4451ceca0000" }).tone, "ok");
  assert.equal(checkSentence({ error: "skill_source_timeout" }).tone, "error");
  const layout = pluginLayout("octryx", "demo", [{ path: "LICENSE" }, { path: "SKILL.md" }]).split("\n");
  assert.equal(layout.at(-1), "        └── SKILL.md");
  assert.equal(layout.at(-2), "        ├── LICENSE");
});

test("a Workspace row reports the least ready delivered surface", () => {
  const ready = { state: "ready", refusals: [] }, restricted = { state: "restricted", refusals: [{ tool: "Bash", policy: "p", reason: "", rule: null }] };
  const summary = reachSummary({ project_id: "p", name: "W", surfaces: {
    platform_chat: { delivered: true, assigned_by: "category:iac", reason: "", readiness: ready },
    octryx_claude: { delivered: true, assigned_by: "category:iac", reason: "", readiness: restricted },
  } });
  assert.deepEqual([summary.delivered, summary.assignedBy, summary.readiness.state], [true, "category:iac", "restricted"]);
  const none = reachSummary({ project_id: "p", name: "W", surfaces: { platform_chat: { delivered: false, assigned_by: "", reason: "not_assigned", readiness: null } } });
  assert.deepEqual([none.delivered, none.readiness], [false, null]);
});
