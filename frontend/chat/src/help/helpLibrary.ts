import { readHelpDocs, type HelpDoc } from "./helpDocs";

const FILES = import.meta.glob("/help/**/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const HELP_DOCS: HelpDoc[] = readHelpDocs(FILES);
