import { readGuidePages, type GuidePage } from "./helpGuides";

// The guides bundled with the UI: every `frontend/chat/guides/<guide>/<page>.md` (helpGuides.ts).
const FILES = import.meta.glob("/guides/**/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const GUIDE_PAGES: GuidePage[] = readGuidePages(FILES);
