import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as presentation from "../../src/admin/components/entityGraph/entityGraphPresentation.ts";
import * as matches from "../../src/admin/components/entityGraph/entityGraphMatches.ts";
import * as types from "../../src/admin/components/entityGraph/entityGraphTypes.ts";
import * as trail from "../../src/admin/components/entityGraph/entityGraphFocusTrail.ts";
import * as noise from "../../src/admin/components/entityGraph/entityGraphNoise.ts";
import * as kgView from "../../src/admin/components/entityGraph/kgView.ts";
import * as kgExpand from "../../src/admin/components/entityGraph/kgExpand.ts";
import * as kgCommunities from "../../src/admin/components/entityGraph/kgCommunities.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function transpile(file, exports, context) {
  const source=fs.readFileSync(new URL(`../../src/admin/components/entityGraph/${file}`,import.meta.url),"utf8");
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText, {exports, ...context});
  return exports;
}
const toolbar = transpile("EntityGraphToolbar.tsx", {}, {require});
const legend = transpile("EntityGraphLegend.tsx", {}, {require(name) {
  if(name.endsWith("kgView")) return kgView;
  return require(name);
}});

const layerFilter = transpile("EntityGraphLayerFilter.tsx", {}, {require(name) {
  if(name.endsWith("entityGraphPresentation")) return presentation;
  return require(name);
}});

const focusBar = transpile("EntityGraphFocusBar.tsx", {}, {require(name) {
  if(name.endsWith("entityGraphFocusTrail")) return trail;
  return require(name);
}});

// The graph's own search field (Advanced also holds a checkbox).
const searchInput=(view)=>view.root.find((node)=>node.type==="input"&&node.props.type==="search");

function harness() {
  const requests=[];
  const exports={};
  const source=fs.readFileSync(new URL("../../src/admin/components/entityGraph/AdminEntityGraphPanel.tsx",import.meta.url),"utf8");
  // The panel's hooks live in their own modules; they get the same stubs as the panel.
  const hooks={};
  const context={URLSearchParams, Error, Set, Map, window:{setTimeout:()=>0,clearTimeout(){}}, require:resolve};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText, {
    exports, ...context});
  function resolve(name) {
    if(name.endsWith("useEntityGraphView")) return hooks.view ??= transpile("useEntityGraphView.ts", {}, context);
    if(name.endsWith("useEntityGraphExpand")) return hooks.expand ??= transpile("useEntityGraphExpand.ts", {}, context);
    if(name.endsWith("useEntityGraphPanelState")) return hooks.panel ??= transpile("useEntityGraphPanelState.ts", {}, context);
    if(name.endsWith("adminPanelHelpers")) return {readJson:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))};
    if(name.endsWith("entityGraphPresentation")) return presentation;
    if(name.endsWith("entityGraphMatches")) return matches;
    if(name.endsWith("entityGraphTypes")) return types;
    if(name.endsWith("kgLayout")) return {layoutGraph:nodes=>({nodes:new Map(nodes.map(node=>[node.id,{x:10,y:10,r:10}])),clusters:[]}),
      egoLayout:(centre,others)=>new Map([centre,...others].map(node=>[node.id,{x:10,y:10,r:10}]))};
    if(name.endsWith("kgView")) return kgView;
    if(name.endsWith("kgExpand")) return kgExpand;
    if(name.endsWith("kgCommunities")) return kgCommunities;
    if(name.endsWith("EntityGraphKindFilter")) return {EntityGraphKindFilter:()=>null};
    if(name.endsWith("EntityGraphLegend")) return legend;
    if(name.endsWith("EntityGraphCanvas")) return {EntityGraphCanvas:({nodes,onFocus,onExpand,freshIds,legend})=>createElement("div",{id:"canvas"},
      nodes.map(node=>node.display_name).join(","),
      createElement("button",{id:"focus-first",onClick:()=>onFocus(nodes[nodes.length-1].id)},"focus"),
      createElement("button",{id:"expand-first",onClick:()=>onExpand(nodes[0].id)},"expand"),
      createElement("span",{id:"fresh"},[...(freshIds||[])].join(",")),legend)};
    if(name.endsWith("EntityGraphFocusBar")) return focusBar;
    if(name.endsWith("entityGraphFocusTrail")) return trail;
    if(name.endsWith("EntityGraphRelationships")) return {EntityGraphRelationships:()=>null};
    if(name.endsWith("EntityGraphToolbar")) return toolbar;
    if(name.endsWith("EntityGraphLayerFilter")) return layerFilter;
    if(name.endsWith("entityGraphNoise")) return noise;
    if(name.endsWith(".css")) return {};
    return require(name);
  }
  const viewsExports = {};
  const viewsSource = fs.readFileSync(new URL("../../src/admin/components/entityGraph/AdminEntityGraphViews.tsx",import.meta.url),"utf8");
  vm.runInNewContext(ts.transpileModule(viewsSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText, {
    exports:viewsExports, require(name) {
      if(name.endsWith("AdminEntityGraphPanel")) return exports;
      if(name.endsWith("KnowledgeSearchPanel")) throw new Error("The graph page must not embed a second search surface.");
      return require(name);
    },
  });
  return {Panel:exports.AdminEntityGraphPanel,Views:viewsExports.AdminEntityGraphViews,requests};
}
function graph(workspace,name) {
  return {store:"extracted_graph",workspace_id:workspace,state:"ok",truncated:false,
    nodes:[{id:name,display_name:name,node_type:"entity",description:"",degree:0,trust_level:"extracted"}],edges:[],
    stats:{shown_nodes:1,shown_edges:0,node_types:{entity:1},scope:"project",total_nodes:null,total_edges:null,total_claims:null,total_communities:null}};
}

test("late graph response from another workspace cannot replace the selected workspace", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"workspace-a"}));});
  act(()=>view.update(createElement(Panel,{projectId:"workspace-b"})));
  assert.match(requests[0].url,/workspaces\/workspace-a\/knowledge\/graph\/explorer/);
  await act(async()=>requests[1].resolve(graph("workspace-b","Current entity")));
  await act(async()=>requests[0].resolve(graph("workspace-a","Stale entity")));
  assert.equal(view.root.findByProps({id:"canvas"}).children[0],"Current entity");
  act(()=>view.unmount());
});

test("configuration state displays next steps without a false zero-node canvas or count",async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"workspace-a"}));});
  await act(async()=>requests[0].resolve({...graph("workspace-a",""),state:"needs_configuration",nodes:[],stats:{shown_nodes:0,shown_edges:0,node_types:{}}}));
  assert.equal(view.root.findAllByProps({id:"canvas"}).length,0);
  assert.match(JSON.stringify(view.toJSON()),/Graph needs configuration/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()),/in this view/);
  act(()=>view.unmount());
});


test("changing workspace remounts graph controls so the previous search cannot filter another workspace", async()=>{
  const {Views,requests}=harness(); let view;
  const props={projectId:"workspace-a",setProjectId:()=>{},projects:[]};
  act(()=>{view=TestRenderer.create(createElement(Views,props));});
  await act(async()=>requests[0].resolve(graph("workspace-a","Entity A")));
  act(()=>searchInput(view).props.onChange({target:{value:"A-only query"}}));
  act(()=>view.root.findByType("form").props.onSubmit({preventDefault(){}}));
  assert.match(requests[1].url,/query=A-only/);
  act(()=>view.update(createElement(Views,{...props,projectId:"workspace-b"})));
  assert.equal(new URL(requests[2].url,"https://local.test").searchParams.has("query"),false);
  assert.equal(searchInput(view).props.value, "");
  act(()=>view.unmount());
});


test("the clustered graph opens with the API's largest window (150) and Advanced still narrows it", () => {
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"workspace-a"}));});
  assert.equal(new URL(requests[0].url,"https://local.test").searchParams.get("max_nodes"), "150");
  const limit = view.root.findByType("select");
  assert.equal(limit.props.value,150);
  act(()=>limit.props.onChange({target:{value:"50"}}));
  assert.equal(new URL(requests[1].url,"https://local.test").searchParams.get("max_nodes"), "50");
  act(()=>view.unmount());
});


const textOf = (node) => (typeof node === "string" ? node : node.children.map(textOf).join(""));

test("the graph page is the graph only: no view switch and no second search surface", async()=>{
  const {Views,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Views,{projectId:"workspace-a",setProjectId:()=>{},projects:[]}));});
  await act(async()=>requests[0].resolve(graph("workspace-a","Entity A")));
  // The canvas mock's own "focus" button is not part of the page chrome.
  const labels=view.root.findAllByType("button").filter((button)=>!["focus-first","expand-first"].includes(button.props.id)).map(textOf);
  // Besides Search: the entity list switch and the graph-layer filter (under Advanced); no second view.
  assert.deepEqual(labels,["Search","Entity list","Manual","Configuration","Operations","Extracted"]);
  assert.equal(view.root.findAllByType("input").filter((input)=>input.props.type==="search").length,1);
  act(()=>view.unmount());
});

test("one count line says how much is drawn; a bounded view says so; reading help sits under Advanced", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"workspace-a"}));});
  const payload={...graph("workspace-a","Jackson 2"),truncated:true};
  payload.nodes=[...payload.nodes,{id:"cbor",display_name:"CBOR",node_type:"entity",description:"",degree:1,trust_level:"extracted"}];
  payload.edges=[{id:"e",source:"cbor",target:"Jackson 2",edge_type:"USES",description:"CBOR uses Jackson 2"}];
  payload.stats={...payload.stats,shown_nodes:2,shown_edges:1,node_types:{entity:2}};
  await act(async()=>requests[0].resolve(payload));
  const count=()=>textOf(view.root.findAll((node)=>node.props.className==="kg-bar__count")[0]);
  assert.equal(count(),"2 entities · 1 relationship");
  assert.match(JSON.stringify(view.toJSON()),/Bounded view/);
  const advanced=view.root.findAll((node)=>node.type==="details"&&String(node.props.className).includes("kg-advanced"))[0];
  assert.equal(advanced.props.open,undefined);
  assert.match(textOf(advanced),/double-click or Expand loads its neighbourhood/);

  act(()=>searchInput(view).props.onChange({target:{value:"jackson"}}));
  act(()=>view.root.findByType("form").props.onSubmit({preventDefault(){}}));
  await act(async()=>requests[1].resolve({...payload,truncated:false,match_ids:["Jackson 2","cbor"],stats:{...payload.stats,matched_nodes:2,match_limit:150}}));
  assert.equal(count(),"2 entities · 1 relationship · 2 matches for “jackson”");
  assert.doesNotMatch(JSON.stringify(view.toJSON()),/Bounded view/);
  act(()=>view.unmount());
});

test("a neighbourhood is named and Back restores the previous search exactly", async()=>{
  const {Panel,requests}=harness(); let view;
  const graphs = (url) => requests.filter((request)=>request.url.includes("/graph/explorer?") || request.url.endsWith("/graph/explorer"));
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"ws"}));});
  await act(async()=>requests[0].resolve(graph("ws","Start")));
  const input = view.root.findByProps({"aria-label":"Search graph entities"});
  act(()=>input.props.onChange({target:{value:"Jackson"}}));
  await act(async()=>view.root.findByProps({role:"search"}).props.onSubmit({preventDefault(){}}));
  const search = graphs().at(-1);
  assert.match(search.url,/query=Jackson/);
  await act(async()=>search.resolve({...graph("ws","Jackson"),nodes:[...graph("ws","Jackson").nodes,{...graph("ws","Jackson 2").nodes[0]}]}));
  await act(async()=>view.root.findByProps({id:"focus-first"}).props.onClick());
  const focus = graphs().at(-1);
  assert.match(focus.url,/Jackson%202|Jackson\+2|Jackson 2/);
  assert.doesNotMatch(focus.url,/query=Jackson(&|$)/);
  await act(async()=>focus.resolve(graph("ws","Jackson 2")));
  // Breadcrumbs: the search, then the neighbourhood it led to.
  const trail = view.root.findByProps({"aria-label":"Graph focus trail"});
  assert.equal(textOf(trail),"“Jackson”›Jackson 2");
  const back = view.root.findAll((node)=>node.type==="button" && String(node.props.title).includes("Back to results for “Jackson”"))[0];
  await act(async()=>back.props.onClick());
  assert.match(graphs().at(-1).url,/query=Jackson/);
  assert.equal(view.root.findByProps({"aria-label":"Search graph entities"}).props.value,"Jackson");
  act(()=>view.unmount());
});

test("Expand adds what is new around an entity to the view; totals give the count line; nothing new is said", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"ws"}));});
  const base={...graph("ws","Hub"),truncated:true};
  base.stats={...base.stats,total_nodes:409,total_edges:915};
  await act(async()=>requests[0].resolve(base));
  const count=()=>textOf(view.root.findAll((node)=>node.props.className==="kg-bar__count")[0]);
  assert.equal(count(),"1 of 409 entities · 0 of 915 relationships");
  assert.doesNotMatch(JSON.stringify(view.toJSON()),/Bounded view/,"totals known: no bounded note");
  await act(async()=>view.root.findByProps({id:"expand-first"}).props.onClick());
  const ask=new URL(requests.at(-1).url,"https://local.test").searchParams;
  assert.equal(ask.get("expand_node_id"),"Hub");
  assert.equal(ask.get("current_node_ids"),"Hub");
  assert.equal(ask.has("focus_node_id"),false);
  const added={...graph("ws","New one"),mode:"expand",additive:true,expand_node_id:"Hub",
    edges:[{id:"e1",source:"Hub",target:"New one",edge_type:"OWNS",description:""}]};
  await act(async()=>requests.at(-1).resolve(added));
  assert.equal(view.root.findByProps({id:"canvas"}).children[0],"Hub,New one","added, the view not replaced");
  assert.equal(view.root.findByProps({id:"fresh"}).children[0],"New one","the new entity is highlighted");
  assert.match(JSON.stringify(view.toJSON()),/1 new around Hub/);
  await act(async()=>view.root.findByProps({id:"expand-first"}).props.onClick());
  assert.equal(new URL(requests.at(-1).url,"https://local.test").searchParams.get("current_node_ids"),"Hub,New one");
  await act(async()=>requests.at(-1).resolve({...graph("ws","x"),nodes:[],state:"no_matches",mode:"expand",additive:true}));
  assert.match(JSON.stringify(view.toJSON()),/Nothing new around Hub/);
  assert.equal(view.root.findByProps({id:"canvas"}).children[0],"Hub,New one");
  act(()=>view.unmount());
});

test("without entity types the legend explains that colours show groups by connection", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"ws"}));});
  const payload=graph("ws","JMS");
  payload.nodes=[...payload.nodes,{id:"jms-q",display_name:"JMS Message Queue",node_type:"entity",description:"",degree:1,trust_level:"extracted"}];
  payload.stats={...payload.stats,node_types:{entity:2}};
  await act(async()=>requests[0].resolve(payload));
  assert.match(JSON.stringify(view.toJSON()),/not classified for this Workspace.*Colours show groups of closely linked entities/);
  act(()=>view.unmount());
});

test("only documents and chapters so far: they are shown with a quiet note instead of 'All entities are hidden'", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"ws"}));});
  const payload=graph("ws","Admin Guide");
  payload.nodes=[{...payload.nodes[0],node_type:"Document"},
    {id:"ch",display_name:"4.4 Database",node_type:"Chapter",description:"",degree:1,trust_level:"deterministic"}];
  payload.edges=[{id:"e",source:"Admin Guide",target:"ch",edge_type:"contains",description:""}];
  payload.stats={...payload.stats,node_types:{Document:1,Chapter:1}};
  await act(async()=>requests[0].resolve(payload));
  const out=JSON.stringify(view.toJSON());
  assert.doesNotMatch(out,/All entities are hidden/);
  assert.equal(view.root.findByProps({id:"canvas"}).children[0],"Admin Guide,4.4 Database");
  assert.match(out,/Only documents and chapters so far – shown because nothing else is extracted yet/);
  act(()=>view.unmount());
});

test("Reset search and filters really resets: hidden types come back", async()=>{
  const {Panel,requests}=harness(); let view;
  act(()=>{view=TestRenderer.create(createElement(Panel,{projectId:"ws"}));});
  const payload=graph("ws","Java");
  payload.nodes=[{...payload.nodes[0],node_type:"Software"},
    {id:"pg",display_name:"PostgreSQL",node_type:"Database",description:"",degree:1,trust_level:"extracted"}];
  payload.stats={...payload.stats,node_types:{Software:1,Database:1}};
  await act(async()=>requests[0].resolve(payload));
  const chip=(type)=>view.root.findAll((node)=>node.type==="button"&&node.props["data-type"]===type)[0];
  act(()=>chip("Software").props.onClick({altKey:false}));
  act(()=>chip("Database").props.onClick({altKey:false}));
  assert.match(JSON.stringify(view.toJSON()),/All entities are hidden/);
  const reset=view.root.findAll((node)=>node.type==="button"&&textOf(node)==="Reset search and filters")[0];
  act(()=>reset.props.onClick());
  assert.equal(view.root.findByProps({id:"canvas"}).children[0],"Java,PostgreSQL");
  act(()=>view.unmount());
});
