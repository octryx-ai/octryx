// Scanner behind designSystemTabs.test.mjs: finds tab-like controls in frontend/chat/src that are not the shared
// SegmentedTabs (layout/SegmentedTabs.ts), the one tab style of the design system.
//
// A finding is
//   - a `role="tab"` / `role="tablist"` (JSX attribute or `role: "tab"` in a createElement prop object), or
//   - an element whose class names a tab bar or a tab: a token ending in `tabs`, `subtabs`, `subnav`, `seg`,
//     `segments` or `pills` on any element, or ending in `tab` on a button, a link or an element with onClick
//     (`admin-channels__tab`, `coding-session-tabs`, `sk-subnav`, `skills__seg`, `ds-segments__tab` written by hand).
// layout/SegmentedTabs.ts is the one place allowed to render them. Side navigation menus whose classes only borrow
// the word (NOT_TABS) are no tabs.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("typescript");

export const SEGMENTED_TABS_FILE = "layout/SegmentedTabs.ts";

// Class tokens that contain the word but are no tabs: the vertical navigation menu of the Admin and Personal settings
// sidebars (with its sub-entries), the composer's dropdown chips and a user's group chips.
export const NOT_TABS = new Set([
  "admin-panel__tab", "admin-panel__subtabs", "admin-panel__subtab", "composer-pill", "user-edit-panel__group-pills",
]);

const BAR = /(^|[_-])(tabs|subtabs|subnav|seg|segments|pills)(--[\w-]+)?$/;
const ITEM = /(^|[_-])(tab|subtab|seg|segment|pill)(--[\w-]+)?$/;
const INTERACTIVE_TAGS = new Set(["button", "a"]);
const ROLE_PROP = /\brole\s*:\s*["'](tab|tablist)["']/g;

const walk = (dir, out = []) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) out.push(full);
  }
  return out;
};

// The class-name tokens of a className attribute: every string literal piece in it, split on spaces.
function classTokens(initializer) {
  if (!initializer) return [];
  const tokens = [];
  const visit = (node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) tokens.push(...node.text.split(/\s+/));
    else if (ts.isTemplateExpression(node)) {
      tokens.push(...node.head.text.split(/\s+/));
      for (const span of node.templateSpans) {
        visit(span.expression);
        tokens.push(...span.literal.text.split(/\s+/));
      }
    } else ts.forEachChild(node, visit);
  };
  visit(initializer);
  return tokens.filter(Boolean);
}

function attribute(element, name) {
  for (const prop of element.attributes.properties) {
    if (ts.isJsxAttribute(prop) && prop.name.getText() === name) return prop;
  }
  return null;
}

// NOT_TABS holds base names; a modifier (`--active`) belongs to its base.
const tabClass = (token, interactive) => !NOT_TABS.has(token.split("--")[0]) && (BAR.test(token) || (interactive && ITEM.test(token)));

/** The tab-like controls of one source file: [{ line, what }]. */
export function tabControls(source, fileName) {
  const kind = fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, kind);
  const found = [];
  const lineOf = (pos) => file.getLineAndCharacterOfPosition(pos).line + 1;
  const visit = (node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText();
      const role = attribute(node, "role")?.initializer;
      if (role && ts.isStringLiteral(role) && (role.text === "tab" || role.text === "tablist")) {
        found.push({ line: lineOf(node.getStart()), what: `<${tag} role="${role.text}">` });
      } else {
        const interactive = INTERACTIVE_TAGS.has(tag) || Boolean(attribute(node, "onClick"));
        const token = classTokens(attribute(node, "className")?.initializer).find((name) => tabClass(name, interactive));
        if (token) found.push({ line: lineOf(node.getStart()), what: `<${tag} className="${token}">` });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  for (const match of source.matchAll(ROLE_PROP)) found.push({ line: lineOf(match.index), what: `role: "${match[1]}"` });
  return found.sort((a, b) => a.line - b.line);
}

/** Every tab-like control under `srcDir` outside SegmentedTabs, keyed by the path relative to it (forward slashes). */
export function scanTabs(srcDir) {
  const result = new Map();
  for (const file of walk(srcDir)) {
    const relative = path.relative(srcDir, file).split(path.sep).join("/");
    if (relative === SEGMENTED_TABS_FILE) continue;
    const found = tabControls(fs.readFileSync(file, "utf8"), file);
    if (found.length) result.set(relative, found);
  }
  return result;
}
