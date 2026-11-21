// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/logoAssets.test.mjs
//
// Perf audit: favicon and logo were 1.39 MB each, an SVG wrapping a 2048 px PNG. They are now the traced
// vector logo (the paths of octryxLogoPaths.ts) in the original colours, so they work in an <img> and as a favicon.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const CHAT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SERVED = ["public/favicon.svg", "public/octryx-logo.svg"];

test("the served logo files are small vector SVGs without an embedded raster", () => {
  const paths = fs.readFileSync(path.join(CHAT, "src/chat/companion/octryxLogoPaths.ts"), "utf8");
  for (const file of SERVED) {
    const svg = fs.readFileSync(path.join(CHAT, file), "utf8");
    assert.doesNotMatch(svg, /<image|data:image|base64/, file);
    assert.ok(svg.length < 16_000, `${file} is ${svg.length} bytes`);
    assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 100 100"/, file);
    // An <img> and a favicon have no currentColor: every path has its own colour.
    const fills = [...svg.matchAll(/<path fill="(#[0-9a-f]{6})" d="([^"]+)"/g)];
    assert.equal(fills.length, 5, file);
    assert.doesNotMatch(svg, /currentColor/, file);
    // The same traced outline as the in-app logo: every subpath of the asset is one of the component's.
    for (const [, , d] of fills) {
      for (const sub of d.split("Z").filter(Boolean)) assert.ok(paths.includes(sub.trim()), `${file}: ${sub.slice(0, 30)}…`);
    }
  }
});

test("the message logo is the vector logo on a round background, without an embedded raster", () => {
  const svg = fs.readFileSync(path.join(CHAT, "public/message-logo.svg"), "utf8");
  assert.doesNotMatch(svg, /<image|data:image|base64/);
  assert.ok(svg.length < 16_000, `message-logo.svg is ${svg.length} bytes`);
  assert.match(svg, /<circle cx="50" cy="50" r="50" fill="#[0-9a-f]{6}"\/>/);
  assert.equal([...svg.matchAll(/<path fill="#[0-9a-f]{6}" d="/g)].length, 5);
});
