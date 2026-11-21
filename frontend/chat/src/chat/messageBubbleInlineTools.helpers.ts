import type { ToolEvent } from "../chatThreadTypes";

export const INLINE_TOOL_EVENT_NAMES = new Set([
  "save_python_script",
  "run_saved_python_script",
  "list_confluence_page_updates",
  "sync_confluence_knowledge_map",
  "create_diagram",
  "edit_diagram",
]);

export function hasInlineToolExecutionEvents(events: ToolEvent[]) {
  return events.some((event) => INLINE_TOOL_EVENT_NAMES.has(event.toolName));
}
