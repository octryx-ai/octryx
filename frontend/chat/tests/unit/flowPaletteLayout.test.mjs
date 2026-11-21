// The step palette takes real space beside the workflow graph and the graph refits once per
// palette toggle. Viewport only: the stored workflow definition is never written.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { createPaletteRefit, PALETTE_REFIT_FALLBACK_MS } from "../../src/admin/components/flowBuilder/flowPaletteRefit.ts";
import * as paletteModel from "../../src/admin/components/flowBuilder/flowPaletteModel.ts";
import { readCssWithImports } from "./cssWithImports.mjs";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const source = (name) => fs.readFileSync(new URL(`../../src/admin/components/flowBuilder/${name}`, import.meta.url), "utf8");

// `honourFrameCancel: false` models a frame callback that runs although it was cancelled.
function harness({ honourFrameCancel = true } = {}) {
  const fits = [];
  const frames = [];
  const timers = [];
  const refit = createPaletteRefit({
    fit: () => fits.push("fit"),
    frame: (callback) => {
      const entry = { callback, cancelled: false };
      frames.push(entry);
      return () => { if (honourFrameCancel) entry.cancelled = true; };
    },
    timer: (callback, ms) => {
      const entry = { callback, ms, cancelled: false };
      timers.push(entry);
      return () => { entry.cancelled = true; };
    },
  });
  const runFrames = () => frames.splice(0).filter((entry) => !entry.cancelled).forEach((entry) => entry.callback());
  const runTimers = () => timers.filter((entry) => !entry.cancelled).splice(0).forEach((entry) => { entry.cancelled = true; entry.callback(); });
  return { refit, fits, frames, timers, runFrames, runTimers };
}

test("a palette toggle fits once, after the graph's width changes and one frame", () => {
  const h = harness();
  h.refit.graphResized(700); // first observation only records the width
  h.refit.paletteToggled();
  assert.equal(h.fits.length, 0, "nothing fits before React Flow has the new size");
  h.refit.graphResized(456);
  assert.equal(h.fits.length, 0, "the fit waits one frame after the resize");
  h.runFrames();
  assert.deepEqual(h.fits, ["fit"]);
  h.runTimers();
  assert.equal(h.fits.length, 1, "the fallback was cancelled; no second fit");
});

test("resizes without a toggle (window resize, pan, selection) never fit", () => {
  const h = harness();
  h.refit.graphResized(700);
  h.refit.graphResized(640);
  h.refit.graphResized(900);
  h.runFrames();
  h.runTimers();
  assert.equal(h.fits.length, 0);
});

test("when the width does not change, the fallback fits once; repeated toggles coalesce", () => {
  const h = harness();
  h.refit.graphResized(700);
  h.refit.paletteToggled();
  h.refit.paletteToggled();
  assert.equal(h.timers.filter((entry) => !entry.cancelled).length, 1, "one pending fallback");
  assert.equal(h.timers.at(-1).ms, PALETTE_REFIT_FALLBACK_MS);
  h.runTimers();
  h.runFrames();
  assert.deepEqual(h.fits, ["fit"]);
  h.refit.graphResized(456);
  h.runFrames();
  assert.equal(h.fits.length, 1, "a later resize does not fit again");
});

test("dispose after the resize cancels the already queued frame (editor unmounts mid-refit)", () => {
  const h = harness();
  h.refit.graphResized(700);
  h.refit.paletteToggled();
  h.refit.graphResized(456); // the fit is now queued for the next frame
  assert.equal(h.frames.length, 1);
  h.refit.dispose();
  assert.equal(h.frames[0].cancelled, true, "the queued frame is cancelled");
  h.runFrames();
  h.runTimers();
  assert.equal(h.fits.length, 0);
});

test("a frame that still runs after dispose does not fit", () => {
  const h = harness({ honourFrameCancel: false });
  h.refit.graphResized(700);
  h.refit.paletteToggled();
  h.refit.graphResized(456);
  h.refit.dispose();
  h.runFrames(); // cancellation ignored by the scheduler: the guard must hold
  assert.equal(h.fits.length, 0);
});

test("nothing resurrects a disposed refit", () => {
  const h = harness();
  h.refit.graphResized(700);
  h.refit.dispose();
  h.refit.paletteToggled();
  h.refit.graphResized(456);
  h.refit.graphResized(700);
  h.runTimers();
  h.runFrames();
  assert.equal(h.fits.length, 0);
  assert.equal(h.timers.length, 0, "no fallback is scheduled after dispose");
  assert.equal(h.frames.length, 0, "no frame is scheduled after dispose");
});

test("dispose drops a pending refit", () => {
  const h = harness();
  h.refit.graphResized(700);
  h.refit.paletteToggled();
  h.refit.dispose();
  h.refit.graphResized(456);
  h.runTimers();
  h.runFrames();
  assert.equal(h.fits.length, 0);
});

function loadPalette() {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source("FlowPalette.tsx"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    require: (name) => {
      if (name.endsWith(".css")) return {};
      if (name.endsWith("/flowPaletteModel")) return paletteModel;
      if (name.endsWith("/FlowPaletteIcons")) return { PaletteIcon: () => null };
      return require(name);
    },
  });
  return exports.FlowPalette;
}

test("opening and closing the palette is reported, closing works while agents load, and nothing is added", () => {
  const FlowPalette = loadPalette();
  const toggles = [];
  const added = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowPalette, {
      onAddNode: (...args) => added.push(args), isCollapsed: true, loading: true, onCollapsedChange: (collapsed) => toggles.push(collapsed),
    }));
  });
  const byLabel = (label) => view.root.findAllByType("button").find((button) => button.props["aria-label"] === label);
  act(() => byLabel("Open the step palette").props.onClick());
  assert.deepEqual(toggles, [false]);
  // Agents are still loading: the loading status shows and the close control stays usable.
  assert.equal(view.root.findAllByProps({ "aria-label": "Loading agents" }).filter((item) => typeof item.type === "string").length, 1);
  const close = byLabel("Close the step palette");
  assert.ok(close, "close is available while loading");
  act(() => close.props.onClick());
  assert.deepEqual(toggles, [false, true]);
  assert.ok(byLabel("Open the step palette"));
  assert.deepEqual(added, [], "toggling never adds a step or touches the workflow");
  act(() => view.unmount());
});

test("the canvas refits only through the viewport and the palette never overlays the graph", () => {
  const canvas = source("FlowCanvas.tsx") + source("useFlowCanvasFit.ts");
  const block = canvas.slice(canvas.indexOf("const paletteRefit"), canvas.indexOf("// Fit view once after initial render"));
  assert.match(block, /fitView\(\{ \.\.\.FIT_VIEW, duration: 250 \}\)/);
  assert.match(block, /return \(\) => window\.cancelAnimationFrame\(id\)/, "the real frame scheduler can be cancelled");
  assert.match(block, /refit\.dispose\(\)/, "unmount disposes the refit");
  assert.doesNotMatch(block, /syncToParent|onChange|setNodes|setEdges/, "the refit path never writes the definition");
  assert.match(canvas, /onCollapsedChange=\{onPaletteCollapsedChange\}/);
  assert.match(canvas, /className="flow-canvas__graph" ref=\{graphRef\}/);
  // The defect itself: an absolutely positioned palette over the graph, a widened collapsed rail on
  // small screens, and toolbar offsets that assumed the overlay.
  const css = readCssWithImports(new URL("../../src/admin/components/flowBuilder/flowBuilderWorkbench.css", import.meta.url)).replace(/\/\*[\s\S]*?\*\//g, "");
  const palette = css.slice(css.indexOf(".flow-palette {"), css.indexOf("}", css.indexOf(".flow-palette {")));
  assert.match(palette, /position: relative/);
  assert.doesNotMatch(palette, /position: absolute/);
  assert.match(css, /\.flow-palette:not\(\.flow-palette--collapsed\) \{\s*width: 160px;/);
  assert.doesNotMatch(css, /\.flow-palette(--collapsed)? ~ \.flow-canvas__graph \.flow-canvas__toolbar/);
});
