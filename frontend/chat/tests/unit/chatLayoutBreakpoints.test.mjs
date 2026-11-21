// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Breakpoint contract for the narrow-viewport chat workspace. The four
// acceptance viewports must resolve to the intended layout mode, and the CSS
// module must not drift away from the TypeScript constants that decide which
// controls are rendered behind a disclosure.
import assert from "node:assert/strict";
import { readCssWithImports } from "./cssWithImports.mjs";
import { test } from "node:test";

import {
  CHAT_LAYOUT_BREAKPOINTS,
  CHAT_LAYOUT_MEDIA_QUERIES,
  isCompactChatLayout,
  resolveChatLayoutMode,
} from "../../src/chat/responsive/chatLayoutBreakpoints.ts";

const COMPACT_SHELL_CSS = readCssWithImports(
  new URL("../../src/styles/chat/chat-compact-shell.css", import.meta.url),
);

test("the four acceptance viewports resolve to their layout mode", () => {
  assert.equal(resolveChatLayoutMode(390), "phone");
  assert.equal(resolveChatLayoutMode(430), "phone");
  assert.equal(resolveChatLayoutMode(768), "compact");
  assert.equal(resolveChatLayoutMode(1440), "desktop");

  // Phone is a subset of compact: shell chrome collapses on both.
  assert.equal(isCompactChatLayout(resolveChatLayoutMode(390)), true);
  assert.equal(isCompactChatLayout(resolveChatLayoutMode(768)), true);
  assert.equal(isCompactChatLayout(resolveChatLayoutMode(1440)), false);
});

test("layout mode switches exactly at the declared breakpoints", () => {
  const { phoneMaxWidth, compactMaxWidth } = CHAT_LAYOUT_BREAKPOINTS;

  assert.equal(resolveChatLayoutMode(phoneMaxWidth), "phone");
  assert.equal(resolveChatLayoutMode(phoneMaxWidth + 1), "compact");
  assert.equal(resolveChatLayoutMode(compactMaxWidth), "compact");
  assert.equal(resolveChatLayoutMode(compactMaxWidth + 1), "desktop");

  // A missing/unmeasured viewport must never collapse the desktop layout.
  assert.equal(resolveChatLayoutMode(Number.NaN), "desktop");
});

test("the compact CSS module uses only the contracted breakpoints", () => {
  const cssWidths = [
    ...COMPACT_SHELL_CSS.matchAll(/max-width:\s*(\d+)px/g),
  ].map((match) => Number(match[1]));

  assert.ok(cssWidths.length > 0, "compact shell CSS declares no media query");
  const contracted = new Set([
    CHAT_LAYOUT_BREAKPOINTS.phoneMaxWidth,
    CHAT_LAYOUT_BREAKPOINTS.compactMaxWidth,
  ]);
  for (const width of cssWidths) {
    assert.ok(
      contracted.has(width),
      `chat-compact-shell.css uses ${width}px, which is not a contracted breakpoint`,
    );
  }
  for (const width of contracted) {
    assert.ok(
      cssWidths.includes(width),
      `chat-compact-shell.css never styles the ${width}px breakpoint`,
    );
  }

  // The hook subscribes to these exact queries.
  assert.equal(
    CHAT_LAYOUT_MEDIA_QUERIES.phone,
    `(max-width: ${CHAT_LAYOUT_BREAKPOINTS.phoneMaxWidth}px)`,
  );
  assert.equal(
    CHAT_LAYOUT_MEDIA_QUERIES.compact,
    `(max-width: ${CHAT_LAYOUT_BREAKPOINTS.compactMaxWidth}px)`,
  );
});
