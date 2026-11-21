// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/modelsPeopleDesignSystem.test.mjs
// Admin › Models and People & sign-in: one tab style (SegmentedTabs), every create flow in a side
// panel over the dimmed list with Cancel and the primary action, and no explanatory text on the pages (it lives in
// help/admin/<page>.md).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ADMIN = path.resolve(HERE, "../../src/admin/components");
const HELP = path.resolve(HERE, "../../help/admin");
const read = (file) => fs.readFileSync(path.join(ADMIN, file), "utf8");

test("create flows open a side panel with Cancel and a primary action", () => {
  for (const file of ["providerTab/AddProviderForm.tsx", "usersTab/AdminUserCreateForm.tsx", "usersTab/IdentityCreatePanel.tsx",
    "usersTab/AdminIdentityProvidersPanel.tsx", "limits/BudgetDrawer.tsx"]) {
    const source = read(file);
    assert.match(source, /<SidePanel/, `${file}: side panel`);
    assert.match(source, />\s*Cancel\s*</, `${file}: Cancel in the footer`);
    assert.match(source, /admin-panel__action-btn--primary/, `${file}: primary action`);
  }
  for (const file of ["usersTab/AdminGroupsPanel.tsx", "usersTab/AdminRolesPanel.tsx"]) {
    assert.match(read(file), /<IdentityCreatePanel/, file);
  }
});

test("no create button turns into Cancel and no create form sits inline on the list", () => {
  for (const file of ["AdminProvidersTab.tsx", "usersTab/AdminUserAccountsPanel.tsx", "usersTab/AdminGroupsPanel.tsx",
    "usersTab/AdminRolesPanel.tsx", "usersTab/AdminIdentityProvidersPanel.tsx"]) {
    const source = read(file);
    assert.doesNotMatch(source, /\? "Cancel" :/, file);
    assert.doesNotMatch(source, /admin-users__form-grid|admin-users__provider-create/, file);
    assert.match(source, /<AdminHeaderActions>/, `${file}: the create button sits in the page header`);
  }
});

test("Defaults and the model panel use the shared segmented tabs", () => {
  assert.match(read("modelSelection/AdminDefaultAndFallback.tsx"), /<SegmentedTabs /);
  assert.doesNotMatch(read("modelSelection/AdminDefaultAndFallback.tsx"), /admin-channels__tab/);
  assert.match(read("modelCatalog/ModelCatalogDrawer.tsx"), /tabs=\{\{/);
  assert.doesNotMatch(read("modelCatalog/ModelCatalogDrawer.tsx"), /role="tab"/);
});

test("the Models and People pages carry no explanatory paragraphs; their help files do", () => {
  for (const file of ["AdminProvidersTab.tsx", "modelCatalog/AdminModelCatalog.tsx", "modelSelection/AdminDefaultAndFallback.tsx",
    "modelSelection/ExplainTurn.tsx", "limits/AdminLimitsAndBudgets.tsx", "limits/UnpricedModelPolicyField.tsx",
    "limits/WorkflowRunCeilingField.tsx", "usersTab/AdminGroupsPanel.tsx", "usersTab/AdminRolesPanel.tsx",
    "usersTab/AdminEffectiveAccessPanel.tsx", "usersTab/AdminIdentityProvidersPanel.tsx"]) {
    const source = read(file);
    assert.doesNotMatch(source, /<p className="admin-panel__hint">\s*[A-Z]/, file);
    assert.doesNotMatch(source, /model-catalog__note|admin-users__roles-text/, file);
  }
  for (const page of ["providers", "modelCatalog", "modelOrder", "runtimeLimits", "users", "identityRoles", "identityGroups",
    "identityProviders", "identityAccess"]) {
    assert.ok(fs.existsSync(path.join(HELP, `${page}.md`)), `help/admin/${page}.md`);
  }
  assert.match(fs.readFileSync(path.join(HELP, "identityProviders.md"), "utf8"), /Register an app at your identity provider/);
  assert.match(fs.readFileSync(path.join(HELP, "modelOrder.md"), "utf8"), /#1 is the platform default/);
});
