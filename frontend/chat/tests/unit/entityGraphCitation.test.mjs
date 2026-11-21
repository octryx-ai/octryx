import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as links from "../../src/chat/evidence/answerSourceLinks.ts";
import * as api from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import * as request from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const exports = {};
const source = fs.readFileSync(new URL("../../src/admin/components/entityGraph/EntityGraphCitation.tsx", import.meta.url), "utf8");
vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText, {
  exports, window:{location:{origin:"https://local.test"}}, require(name) {
    if (name.endsWith("answerSourceLinks")) return links;
    if (name.endsWith("workspaceKnowledgeApi")) return api;
    if (name.endsWith("workspaceKnowledgeRequest")) return request;
    return require(name);
  },
});
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("graph citation opens retained revision first even when an original website exists", () => {
  let view;
  act(() => { view = TestRenderer.create(createElement(exports.EntityGraphCitation, {
    workspaceId:"workspace/a", evidence:{source_id:"source/b",revision_id:"revision/c",citation:"Guide revision 2",
      section:"Configuration",source_url:"https://example.test/guide",cite_as:"[Guide](javascript:alert(1))"},
  })); });
  const anchors = view.root.findAllByType("a");
  assert.equal(anchors.length,2);
  assert.equal(anchors[0].children[0], "Open captured source");
  assert.equal(anchors[0].props.href, "/api/v1/workspaces/workspace%2Fa/knowledge/sources/source%2Fb/revisions/revision%2Fc/original");
  assert.equal(anchors[1].children[0], "Original website");
  assert.equal(anchors[1].props.href, "https://example.test/guide");
  assert.match(JSON.stringify(view.toJSON()), /Configuration/);
  act(() => view.unmount());
});

test("graph citation never invents a retained link or renders unsafe website URLs", () => {
  let view;
  act(() => { view = TestRenderer.create(createElement(exports.EntityGraphCitation, {
    workspaceId:"workspace", evidence:{source_id:"source",source_url:"javascript:alert(1)",cite_as:"https://example.test/unverified"},
  })); });
  assert.equal(view.root.findAllByType("a").length,0);
  assert.match(JSON.stringify(view.toJSON()), /Captured source link unavailable/);
  act(() => view.unmount());
});
