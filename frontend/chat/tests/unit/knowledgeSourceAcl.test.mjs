import assert from "node:assert/strict";
import { test } from "node:test";
import {
  sourceAclBody, sourceAclDoneText, sourceAclOf, sourceAclPanelView, sourceAclPreviewOf, sourceAclRefusal, sourceAclSummary,
} from "../../src/admin/components/workspaceKnowledge/sourceAcl/sourceAclModel.ts";
import { knowledgeSourcesAccess } from "../../src/admin/components/workspaceKnowledge/sourceAcl/knowledgeSourcesAccess.ts";
import { ADMIN_AREA_CONFIGS, WORKSPACE_ADMIN_ENTRY_AREAS, isAdminTabRefVisible } from "../../src/admin/config/adminPanelAreas.ts";
import { restCatalogOf, visibilityRule } from "../../src/admin/components/workspaceKnowledge/rest/restSourceRules.ts";
import { restSampleView } from "../../src/admin/components/workspaceKnowledge/rest/restSourceSample.ts";
import { requestedSourceAcl, sourceAclHref } from "../../src/admin/components/workspaceKnowledge/sourceLinks.ts";

// Backend: GET/PUT …/knowledge/source-acl, GET …/knowledge/rest-sources, and the sample's per-item excerpt.

const OFF = { workspace_id: "w1", enforce: false, withheld_restricted_items: 3, released_when_enabled: 3, note: "server note" };

test("the switch shows its state and the held-back count as an upper bound", () => {
  const acl = sourceAclOf(OFF);
  assert.deepEqual(acl, { enforce: false, heldBack: 3 });
  const off = sourceAclSummary(acl);
  assert.equal(off.label, "Off");
  assert.equal(off.heldBack, "Up to 3 items are held back.");
  assert.match(off.note, /upper bound.*cannot resolve/);
  assert.equal(sourceAclSummary({ enforce: false, heldBack: 0 }).note, null);
  // On, before the next sync: still counted, and the next sync picks them up.
  assert.match(sourceAclSummary({ enforce: true, heldBack: 1 }).heldBack, /^1 item is still held back\. Each source's next sync picks them up/);
  assert.equal(sourceAclSummary({ enforce: true, heldBack: 0 }).note, null);
  assert.equal(sourceAclOf({ detail: "x" }), null);
});

test("Preview needs a reason, the change a preview of the other state; the body carries reason and dry_run", () => {
  const acl = sourceAclOf(OFF);
  const blank = sourceAclPanelView({ acl, reason: "  ", preview: null, busy: false });
  assert.equal(blank.target, true);
  assert.equal(blank.actionLabel, "Turn on");
  assert.equal(blank.previewEnabled, false);
  assert.equal(blank.confirmEnabled, false);
  assert.equal(blank.waiting, "Enter a reason to continue.");

  const reasoned = sourceAclPanelView({ acl, reason: "Desk articles", preview: null, busy: false });
  assert.equal(reasoned.previewEnabled, true);
  assert.equal(reasoned.confirmEnabled, false);
  assert.equal(reasoned.waiting, "Run the preview first.");

  const preview = sourceAclPreviewOf({ ...OFF, requested: true, changed: true, dry_run: true });
  const ready = sourceAclPanelView({ acl, reason: "Desk articles", preview, busy: false });
  assert.equal(ready.confirmEnabled, true);
  assert.match(ready.previewText, /lets up to 3 items in\. Each source's next sync picks them up/);
  assert.equal(sourceAclPanelView({ acl, reason: "Desk articles", preview, busy: true }).confirmEnabled, false);
  // A preview of a no-op never enables the change.
  const noop = sourceAclPreviewOf({ ...OFF, requested: true, changed: false, released_when_enabled: 0 });
  assert.equal(sourceAclPanelView({ acl, reason: "x", preview: noop, busy: false }).confirmEnabled, false);
  // Turning it off offers "Turn off" and says what happens.
  const on = { enforce: true, heldBack: 0 };
  const offPreview = sourceAclPreviewOf({ enforce: true, requested: false, changed: true, released_when_enabled: 0 });
  const offView = sourceAclPanelView({ acl: on, reason: "audit", preview: offPreview, busy: false });
  assert.equal(offView.actionLabel, "Turn off");
  assert.match(offView.previewText, /holds restricted items back again/);

  assert.deepEqual(sourceAclBody(true, "  Desk articles ", true), { enforce: true, reason: "Desk articles", dry_run: true });
  assert.deepEqual(sourceAclBody(true, "Desk articles", false), { enforce: true, reason: "Desk articles", dry_run: false });
  assert.match(sourceAclDoneText(true), /next sync picks up the held-back items/);
});

test("every refusal of the switch reads in words", () => {
  assert.match(sourceAclRefusal({ status: 422, reason: null }), /^Enter a reason/);
  assert.match(sourceAclRefusal({ status: 403, reason: "source_acl_enforce_admin_only" }), /^Only a platform admin/);
  assert.match(sourceAclRefusal({ status: 404, reason: null }), /not available to you/);
  assert.match(sourceAclRefusal({ status: 409, reason: null }), /did not accept/);
  assert.match(sourceAclRefusal(new Error("Failed to fetch")), /Check your connection/);
});

test("Sources in the nav: platform admin and Workspace owner/admin, not a member; the switch only for a platform admin", () => {
  const ref = ADMIN_AREA_CONFIGS.knowledge.groups.flatMap((group) => group.tabs).find((tab) => tab.id === "workspaceKnowledge");
  assert.equal(isAdminTabRefVisible(ref, true, {}, true), true);
  assert.equal(isAdminTabRefVisible(ref, false, {}, true), true);
  assert.equal(isAdminTabRefVisible(ref, false, {}, false), false);
  // The menu asks for the Workspace role in Knowledge too, not only in Operations.
  assert.ok(WORKSPACE_ADMIN_ENTRY_AREAS.has("knowledge"));
  // The rest of Knowledge's admin pages stay platform admin only.
  const packages = ADMIN_AREA_CONFIGS.knowledge.groups.flatMap((group) => group.tabs).find((tab) => tab.id === "knowledgePackages");
  assert.equal(isAdminTabRefVisible(packages, false, {}, true), false);

  assert.deepEqual(knowledgeSourcesAccess(true), { workspaceVisibility: true, aclSwitch: true, aclNotice: "link" });
  assert.deepEqual(knowledgeSourcesAccess(false), { workspaceVisibility: false, aclSwitch: false, aclNotice: "ask" });
  assert.equal(visibilityRule(false).workspaceAllowed, false);
  assert.match(visibilityRule(false).hint, /platform admin/);

  const href = sourceAclHref("w 1");
  assert.equal(requestedSourceAcl(href.slice(href.indexOf("?"))), true);
  assert.match(href, /tab=workspaceKnowledge&workspace_id=w%201/);
});

test("the dry run shows each visible item's masked excerpt, never a hidden item's", () => {
  const view = restSampleView({
    items: [
      { external_id: "A-1", title: "Reset", excerpt: "## Steps Hold the key. Token [redacted] stays out.", acl: { audience: "scope" } },
      { external_id: "A-2", title: "Detail failed", excerpt: null, excerpt_reason: "custom_rest_detail_out_of_scope", acl: { audience: "scope" } },
      { external_id: "A-3", title: "Binary", excerpt: null, acl: { audience: "scope" } },
      { external_id: "A-4", hidden: true, acl: { audience: "restricted", principals: ["role:operator"] } },
    ],
    listed: 4,
  });
  const [first, failed, binary, hidden] = view.rows;
  assert.equal(first.excerpt, "Steps Hold the key. Token [redacted] stays out.");
  assert.equal(first.excerptNote, null);
  assert.equal(failed.excerpt, null);
  assert.match(failed.excerptNote, /could not be read: the role's result filter refused/);
  assert.match(binary.excerptNote, /not text/);
  assert.deepEqual([hidden.excerpt, hidden.excerptNote], [null, null]);
});

test("the REST catalog offers APIs by key, with their read operations and roles", () => {
  const apis = restCatalogOf({ workspace_id: "w1", definitions: [
    { key: "faqdesk", name: "FAQ desk", connection: "global", operations: [
      { op_key: "list_faqs", name: "list_faqs", method: "GET", path: "/faqs", roles: ["operator"], scoped_roles: [], role_required: false, paginated: true },
    ] },
    { key: "nowhere", name: "Not here", connection: null, operations: [] },
  ] });
  assert.deepEqual(apis.map((api) => [api.id, api.connected]), [["faqdesk", true], ["nowhere", false]]);
  assert.deepEqual(apis[0].operations[0].roles, ["operator"]);
  assert.equal(apis[0].operations[0].paginated, true);
  assert.deepEqual(restCatalogOf({ detail: "nope" }), []);
});
