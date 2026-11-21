// Scanner behind designSystemControls.test.mjs: finds form controls and buttons in frontend/chat/src that render with
// browser-default styling instead of the design system (design guide 9.1, 9.2, 9.6).
//
// A control is `<select>`, `<textarea>`, `<button>` or an `<input>` of type text, number, search, email, password, url,
// radio or checkbox (or without a static type). It passes when
//   - it carries a design-system control class (DS_CONTROL_CLASSES), or sits inside a JSX element with a
//     design-system container class that skins its controls (DS_CONTAINER_CLASSES), or
//   - outside the strict areas (STRICT_DIRS) only: it carries a feature class that a stylesheet skins (a rule on that
//     class sets a border, background, accent-color, appearance or box-shadow), or sits inside an element whose
//     class skins that tag through a descendant rule (`.x select { border: … }`).
// In STRICT_DIRS only the design-system classes count. Everything else is a raw control.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("typescript");

export const DS_CONTROL_CLASSES = new Set([
  "admin-panel__input", "admin-panel__form-input", "admin-panel__textarea", "admin-users__toolbar-select", "admin-users__toolbar-input",
  "admin-panel__action-btn", "admin-panel__button", "admin-panel__danger-btn", "work-area__button", "work-area__nav-button",
  "work-area__collapse", "area-rail__btn", "admin-option-card", "admin-panel__tab", "composer-pill",
]);
export const DS_CONTAINER_CLASSES = new Set([
  "admin-panel__field", "admin-form-grid", "admin-card", "admin-panel__form", "admin-panel__checkbox", "admin-option-card",
  "work-area__filters",
]);
// Strict areas: only design-system classes count here.
export const STRICT_DIRS = ["chat/agents/"];

const CONTROL_TAGS = new Set(["select", "textarea", "button", "input"]);
const INPUT_TYPES = new Set(["", "text", "number", "search", "email", "password", "url", "radio", "checkbox"]);
const SKIN = /(^|[;{\s])(border|border-color|background|background-color|accent-color|appearance|-webkit-appearance|box-shadow)\s*:/;
const STATE_PSEUDO = /:(hover|focus|focus-visible|focus-within|active|disabled|checked|not)\b|::/;

const walk = (dir, ext, out = []) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, ext, out);
    else if (full.endsWith(ext)) out.push(full);
  }
  return out;
};

/** Classes a stylesheet skins: `own` for the element itself, `within[tag]` for a tag inside an element with the class. */
export function skinnedClasses(cssText) {
  const own = new Set();
  const within = { select: new Set(), textarea: new Set(), button: new Set(), input: new Set() };
  const css = cssText.replace(/\/\*[\s\S]*?\*\//g, "").replace(/@import[^;]*;/g, "");
  for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!SKIN.test(rule[2])) continue;
    for (const raw of rule[1].split(",")) {
      const selector = raw.trim();
      if (!selector || selector.startsWith("@")) continue;
      const parts = selector.split(/\s*[>+~]\s*|\s+/).filter(Boolean);
      const last = parts[parts.length - 1];
      if (STATE_PSEUDO.test(last)) continue;
      for (const match of last.matchAll(/\.([\w-]+)/g)) own.add(match[1]);
      const tag = last.match(/^(input|select|textarea|button)\b/)?.[1];
      if (!tag) continue;
      for (const part of parts.slice(0, -1)) for (const match of part.matchAll(/\.([\w-]+)/g)) within[tag].add(match[1]);
    }
  }
  return { own, within };
}

const tokens = (text) => (text ? [...text.matchAll(/[A-Za-z_][\w-]*/g)].map((match) => match[0]) : []);

function attribute(element, name) {
  for (const prop of element.attributes.properties) {
    if (ts.isJsxAttribute(prop) && prop.name.getText() === name) return prop.initializer ? prop.initializer.getText() : "";
  }
  return null;
}

/** The raw controls of one TSX source: [{ line, tag, type, className }]. */
export function rawControls(source, fileName, skins, strict = false) {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found = [];
  const visit = (node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText();
      const typeText = attribute(node, "type");
      const type = typeText && /^["']/.test(typeText) ? typeText.slice(1, -1) : "";
      if (CONTROL_TAGS.has(tag) && (tag !== "input" || INPUT_TYPES.has(type))) {
        const className = attribute(node, "className");
        const own = tokens(className);
        let ok = own.some((token) => DS_CONTROL_CLASSES.has(token) || (!strict && skins.own.has(token)));
        for (let parent = node.parent; !ok && parent; parent = parent.parent) {
          if (!ts.isJsxElement(parent)) continue;
          ok = tokens(attribute(parent.openingElement, "className"))
            .some((token) => DS_CONTAINER_CLASSES.has(token) || (!strict && skins.within[tag].has(token)));
        }
        if (!ok) {
          const line = file.getLineAndCharacterOfPosition(node.getStart()).line + 1;
          found.push({ line, tag, type, className: className ?? "" });
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/** Every raw control under `srcDir`, keyed by the file path relative to it (forward slashes). */
export function scanSources(srcDir) {
  const skins = skinnedClasses(walk(srcDir, ".css").map((file) => fs.readFileSync(file, "utf8")).join("\n"));
  const result = new Map();
  for (const file of walk(srcDir, ".tsx")) {
    const relative = path.relative(srcDir, file).split(path.sep).join("/");
    const strict = STRICT_DIRS.some((dir) => relative.startsWith(dir));
    const found = rawControls(fs.readFileSync(file, "utf8"), file, skins, strict);
    if (found.length) result.set(relative, found);
  }
  return result;
}
