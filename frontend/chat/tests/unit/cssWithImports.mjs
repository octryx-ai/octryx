// Reads a stylesheet with its local `@import "./partial.css";` lines replaced by the partials' text, in order.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const LOCAL_IMPORT = /^@import\s+["'](\.{1,2}\/[^"']+\.css)["'];[ \t]*$/gm;

export function readCssWithImports(file) {
  const full = file instanceof URL ? fileURLToPath(file) : file;
  return fs.readFileSync(full, "utf8").replace(LOCAL_IMPORT, (_line, relative) =>
    readCssWithImports(path.resolve(path.dirname(full), relative)).replace(/\n$/, ""),
  );
}
