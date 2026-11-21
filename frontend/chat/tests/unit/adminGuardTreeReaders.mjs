// Shared helpers of the admin render guards (adminRenderGuards*), on top of adminGuardRenderers / adminGuardStubLoader: a host-node
// count and a button finder by its text.
import { text } from "./settingsRenderHarness.mjs";

/** The number of host (DOM) nodes, stub nodes included: a split that adds or drops a wrapper changes it. */
export const hostCount = (view) => view.root.findAll((node) => typeof node.type === "string").length;

/** The first button whose text is `label`. */
export const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label)[0];
