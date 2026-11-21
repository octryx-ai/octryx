// Shared helpers of the admin render guards (adminRenderGuards*): renderers and tree readers.
import assert from "node:assert/strict";
import TestRenderer from "react-test-renderer";
import { act, text, tick } from "./settingsRenderHarness.mjs";

export function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

export async function createAsync(element) {
  let view;
  await act(async () => { view = TestRenderer.create(element); });
  await tick();
  return view;
}

export const noop = () => {};
export const all = (view, type) => view.root.findAll((node) => node.type === type);
export const buttons = (view) => all(view, "button").map((node) => text(node));
/** Values made in the loaded modules' realm, compared by structure. */
export const plain = (value) => JSON.parse(JSON.stringify(value));
export const includesAll = (page, parts) => { for (const part of parts) assert.ok(page.includes(part), part); };
export const testIds = (view) => [...new Set(view.root.findAll((node) => typeof node.type === "string" && node.props["data-testid"])
  .map((node) => node.props["data-testid"]))];
