const SAFE_SVG_TAGS = new Set([
  "svg",
  "g",
  "path",
  "circle",
  "ellipse",
  "rect",
  "line",
  "polyline",
  "polygon",
  "defs",
  "linearGradient",
  "radialGradient",
  "stop",
  "title",
  "desc",
  "clipPath",
  "mask",
]);

const SAFE_SVG_ATTRS = new Set([
  "aria-hidden",
  "clip-path",
  "clip-rule",
  "cx",
  "cy",
  "d",
  "fill",
  "fill-opacity",
  "fill-rule",
  "gradientTransform",
  "gradientUnits",
  "height",
  "id",
  "mask",
  "offset",
  "opacity",
  "points",
  "preserveAspectRatio",
  "r",
  "role",
  "rx",
  "ry",
  "spreadMethod",
  "stop-color",
  "stop-opacity",
  "stroke",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-miterlimit",
  "stroke-opacity",
  "stroke-width",
  "transform",
  "viewBox",
  "width",
  "x",
  "x1",
  "x2",
  "xmlns",
  "y",
  "y1",
  "y2",
]);

const SAFE_SVG_TEXT_TAGS = new Set(["title", "desc"]);
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const SVG_XML_DECLARATION = /^\s*<\?xml[^>]*\?>/i;
const SVG_LOCAL_FRAGMENT = /^url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]*\s*\)$/;
const SVG_ID = /^[A-Za-z_][A-Za-z0-9_.:-]*$/;
const REJECTED_SVG_VALUE_TOKENS = [
  "javascript:",
  "vbscript:",
  "<",
  ">",
  "expression(",
];

function isSafeSvgAttrValue(attrName: string, value: string) {
  const normalized = value.trim();
  if (!normalized) {
    return true;
  }
  const lowered = normalized.toLowerCase();
  if (REJECTED_SVG_VALUE_TOKENS.some((token) => lowered.includes(token))) {
    return false;
  }
  if (
    ["fill", "stroke", "clip-path", "mask"].includes(attrName) &&
    lowered.startsWith("url(")
  ) {
    return SVG_LOCAL_FRAGMENT.test(normalized);
  }
  if (lowered.includes("url(")) {
    return false;
  }
  if (attrName === "id") {
    return SVG_ID.test(normalized);
  }
  if (attrName === "xmlns") {
    return normalized === SVG_NAMESPACE;
  }
  return true;
}

export function sanitizeInlineSvgMarkup(markup: string): string | null {
  const rawSvg = markup.trim();
  if (!rawSvg || rawSvg.length > 20_000 || typeof DOMParser === "undefined") {
    return null;
  }
  const strippedSvg = rawSvg.replace(SVG_XML_DECLARATION, "").trim();
  const lowered = strippedSvg.toLowerCase();
  if (lowered.includes("<!doctype") || lowered.includes("<!entity")) {
    return null;
  }

  const parser = new DOMParser();
  const document = parser.parseFromString(strippedSvg, "image/svg+xml");
  if (document.querySelector("parsererror")) {
    return null;
  }
  const root = document.documentElement;
  if (!root || root.localName !== "svg") {
    return null;
  }
  if (![null, "", SVG_NAMESPACE].includes(root.namespaceURI)) {
    return null;
  }

  const elements = root.querySelectorAll("*");
  for (const element of [root, ...Array.from(elements)]) {
    if (![null, "", SVG_NAMESPACE].includes(element.namespaceURI)) {
      return null;
    }
    if (!SAFE_SVG_TAGS.has(element.localName)) {
      return null;
    }
    if (
      element.childNodes.length > 0 &&
      Array.from(element.childNodes).some((node) => {
        if (node.nodeType !== Node.TEXT_NODE) {
          return false;
        }
        return (
          node.textContent?.trim() && !SAFE_SVG_TEXT_TAGS.has(element.localName)
        );
      })
    ) {
      return null;
    }
    for (const attr of Array.from(element.attributes)) {
      if (attr.namespaceURI) {
        return null;
      }
      if (attr.name.startsWith("on") || attr.name === "style") {
        return null;
      }
      if (
        !SAFE_SVG_ATTRS.has(attr.name) ||
        !isSafeSvgAttrValue(attr.name, attr.value)
      ) {
        return null;
      }
    }
  }

  return new XMLSerializer().serializeToString(root);
}
