// Render harness for the flow render guards: a light React Flow stand-in that renders its props as data attributes, a
// window stub, and a loader that transpiles a component and its relative imports into a VM.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createElement, useState } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
export const { act } = TestRenderer;
export { TestRenderer };
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
export const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
export const byTestId = (root, id) => root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
export const buttons = (root) => root.findAll((node) => node.type === "button").map((node) => text(node));
export const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

// A light React Flow: the canvas renders its nodes and edges as data attributes and its children.
const stateHook = (initial) => { const [value, setValue] = useState(initial); return [value, setValue, () => {}]; };
const xyflowKnown = {
  ReactFlowProvider: ({ children }) => children,
  ReactFlow: ({ nodes, edges, children, minZoom }) => createElement("div", {
    "data-testid": "rf", "data-min-zoom": minZoom, "data-nodes": nodes.map((node) => node.id).join(","),
    "data-edges": edges.map((edge) => `${edge.id}${edge.label ? `=${edge.label}` : ""}`).join(","),
  }, children),
  BackgroundVariant: { Dots: "dots", Lines: "lines" },
  Controls: () => createElement("div", { "data-testid": "rf-controls" }),
  MiniMap: () => createElement("div", { "data-testid": "rf-minimap" }),
  useNodesState: stateHook,
  useEdgesState: stateHook,
  useReactFlow: () => ({ fitView: () => {}, screenToFlowPosition: (point) => point, getViewport: () => ({ x: 0, y: 0, zoom: 1 }) }),
  applyNodeChanges: (_changes, nodes) => nodes,
  applyEdgeChanges: (_changes, edges) => edges,
  addEdge: (edge, edges) => [...edges, edge],
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
  MarkerType: { Arrow: "arrow", ArrowClosed: "arrowclosed" },
};
export const xyflow = new Proxy(xyflowKnown, {
  get: (target, name) => (name in target ? target[name] : typeof name === "string" && /^use/.test(name) ? () => ({}) : () => null),
});

export function windowStub(search = "") {
  return {
    location: { origin: "http://localhost", pathname: "/chat", search, hash: "", href: `http://localhost/chat${search}` },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    history: { state: null, replaceState: () => {}, pushState: () => {} },
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {},
    setTimeout: (callback, ms) => setTimeout(callback, ms), clearTimeout: (id) => clearTimeout(id),
    requestAnimationFrame: () => 0, cancelAnimationFrame: () => {}, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    innerWidth: 1280,
  };
}

// Transpiles a component and its relative imports into a VM; `stubs` replace modules by exact name or path suffix.
export function loader(globals, stubs = {}) {
  const cache = new Map();
  const stubFor = (name) => Object.entries(stubs).find(([key]) => name === key || (key.startsWith("/") && name.endsWith(key)))?.[1];
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setInterval, clearInterval, setTimeout, clearTimeout, Set, Map, Array, String, Boolean, RegExp,
      structuredClone, crypto: globalThis.crypto, requestAnimationFrame: () => 0, cancelAnimationFrame: () => {}, document: { activeElement: null, addEventListener() {}, removeEventListener() {},
        querySelector: () => null, body: {}, documentElement: { dataset: {} } },
      ...globals,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        const stub = stubFor(name);
        if (stub) return stub;
        if (name.startsWith(".") && name.endsWith(".json")) return JSON.parse(fs.readFileSync(path.resolve(path.dirname(file), name), "utf8"));
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const candidate of [`${base}.tsx`, `${base}.ts`, path.join(base, "index.ts")]) {
            if (fs.existsSync(candidate)) return loadFile(candidate);
          }
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}
