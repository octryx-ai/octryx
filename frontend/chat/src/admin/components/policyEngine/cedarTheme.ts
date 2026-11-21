// The Cedar editor's Monaco themes from the design tokens ("no white editor"). Monaco cannot read
// CSS custom properties, so the hex values are read from the document when the editor mounts; the theme follows
// `data-theme` (dark default, light). Token colours match the read-only Cedar view (cedarHighlight).

type ThemeApi = { editor: { defineTheme: (name: string, data: unknown) => void } };

export const CEDAR_THEME_DARK = "octryx-cedar-dark";
export const CEDAR_THEME_LIGHT = "octryx-cedar-light";

const FALLBACK: Record<string, Record<string, string>> = {
  dark: { "--bg": "#0e100f", "--text": "#efece4", "--muted": "#898f86", "--muted-strong": "#cbc7bc", "--status-error-ink": "#fca5a5", "--status-active-ink": "#9ae6b4", "--status-running-ink": "#bae6fd" },
  light: { "--bg": "#f5f1e8", "--text": "#1a1d1c", "--muted": "#7a8076", "--muted-strong": "#555a53", "--status-error-ink": "#b91c1c", "--status-active-ink": "#0d5132", "--status-running-ink": "#075985" },
};

export function hostTheme(): "dark" | "light" {
  return typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function tokenColor(name: string, theme: "dark" | "light" = hostTheme()): string {
  const value = typeof document !== "undefined" ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() : "";
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value : FALLBACK[theme][name];
}

export function cedarThemeData(theme: "dark" | "light", color: (name: string) => string) {
  const bare = (name: string) => color(name).slice(1);
  return {
    base: theme === "dark" ? "vs-dark" : "vs",
    inherit: true,
    rules: [
      { token: "keyword", foreground: bare("--status-error-ink") },
      { token: "string", foreground: bare("--status-active-ink") },
      { token: "string.quote", foreground: bare("--status-active-ink") },
      { token: "annotation", foreground: bare("--status-running-ink") },
      { token: "comment", foreground: bare("--muted"), fontStyle: "italic" },
      { token: "type", foreground: bare("--text") },
      { token: "identifier", foreground: bare("--muted-strong") },
    ],
    colors: {
      "editor.background": color("--bg"),
      "editor.foreground": color("--muted-strong"),
      "editorLineNumber.foreground": color("--muted"),
      "editorGutter.background": color("--bg"),
    },
  };
}

/** Define both themes (idempotent) and return the one matching the page. */
export function applyCedarThemes(monaco: ThemeApi): string {
  for (const theme of ["dark", "light"] as const) {
    monaco.editor.defineTheme(theme === "dark" ? CEDAR_THEME_DARK : CEDAR_THEME_LIGHT, cedarThemeData(theme, (name) => tokenColor(name, theme)));
  }
  return hostTheme() === "dark" ? CEDAR_THEME_DARK : CEDAR_THEME_LIGHT;
}
