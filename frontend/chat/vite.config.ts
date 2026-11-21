import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

function getPackageName(id: string) {
  const nodeModulesIndex = id.lastIndexOf("node_modules/");
  if (nodeModulesIndex === -1) {
    return null;
  }
  const path = id.slice(nodeModulesIndex + "node_modules/".length);
  if (path.startsWith("@")) {
    const [scope, name] = path.split("/");
    return scope && name ? `${scope}/${name}` : null;
  }
  const [name] = path.split("/");
  return name || null;
}

const TOOLS_CONFIG_GUARD = "tools-config-guard";

// The server-rendered admin pages (templates/base.html) link this stylesheet by a fixed name.
// The build emits it from its one source file, so every consumer of `npm run build` (dev-start.sh
// and the Docker image's chat-frontend-build stage) ships the same file.
const ADMIN_PAGES_STYLESHEET = "admin-design-tokens.css";
const ADMIN_PAGES_STYLESHEET_SOURCE = resolve(__dirname, "src/styles/chat", ADMIN_PAGES_STYLESHEET);

// The source is an entry of local `@import "./partial.css";` lines; the emitted file inlines them in
// order (recursively), so the server-rendered pages still load one stylesheet.
const LOCAL_CSS_IMPORT = /^@import\s+["'](\.{1,2}\/[^"']+\.css)["'];[ \t]*$/gm;

function inlineLocalCssImports(file: string, watch: (path: string) => void): string {
  watch(file);
  return readFileSync(file, "utf8").replace(LOCAL_CSS_IMPORT, (_line, relative: string) =>
    inlineLocalCssImports(resolve(dirname(file), relative), watch).replace(/\n$/, ""),
  );
}

function adminPagesStylesheet(): Plugin {
  return {
    name: "admin-pages-stylesheet",
    apply: "build",
    buildStart() {
      inlineLocalCssImports(ADMIN_PAGES_STYLESHEET_SOURCE, (path) => this.addWatchFile(path));
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: ADMIN_PAGES_STYLESHEET,
        source: inlineLocalCssImports(ADMIN_PAGES_STYLESHEET_SOURCE, () => {}),
      });
    },
  };
}

export default defineConfig({
  base: "/admin/static/chat/",
  plugins: [react(), adminPagesStylesheet()],
  worker: {
    format: "es",
  },
  // cedar-wasm locates its .wasm next to its module (`new URL(..., import.meta.url)`); pre-bundling would move
  // the module away from the file in dev. The build emits the .wasm as an asset either way.
  optimizeDeps: {
    exclude: ["@cedar-policy/cedar-wasm"],
  },
  build: {
    outDir: resolve(__dirname, "../../backend/app/web/static/chat"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        "diagram-preview": resolve(__dirname, "diagram-preview.html"),
        // Octryx Mobile, the Home Screen app: served by the backend at /m (web/routers/mobile_app.py).
        mobile: resolve(__dirname, "m/index.html"),
        // Loaded by the server-rendered /admin/tools page (tools.html) under a fixed name.
        [TOOLS_CONFIG_GUARD]: resolve(__dirname, "src/admin/toolsConfigGuard/toolsConfigGuard.ts"),
      },
      output: {
        entryFileNames: (chunk) =>
          chunk.name === TOOLS_CONFIG_GUARD
            ? `guards/${TOOLS_CONFIG_GUARD}.js`
            : "assets/[name]-[hash].js",
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          const packageName = getPackageName(id);
          if (!packageName) {
            return "vendor";
          }
          if (
            packageName === "@iconify/react" ||
            packageName.startsWith("@iconify-json/") ||
            packageName === "simple-icons"
          ) {
            return "icons";
          }
          if (
            packageName === "react" ||
            packageName === "react-dom" ||
            packageName === "scheduler"
          ) {
            return "react-core";
          }
          if (packageName === "react-virtuoso") {
            return "timeline";
          }
          if (packageName === "@mintplex-labs/piper-tts-web") {
            return "tts";
          }
          if (
            packageName === "react-syntax-highlighter" ||
            packageName === "refractor" ||
            packageName === "prismjs"
          ) {
            return "syntax";
          }
          return "vendor";
        },
      },
    },
  },
});
