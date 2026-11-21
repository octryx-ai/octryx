import { readHelpDocs, type HelpDoc } from "./helpDocs";

// The help files bundled with the UI: every `frontend/chat/help/**/*.md`. Adding or editing a file changes the
// help without touching code (helpDocs.ts).
const FILES = import.meta.glob("/help/**/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const HELP_DOCS: HelpDoc[] = readHelpDocs(FILES);
