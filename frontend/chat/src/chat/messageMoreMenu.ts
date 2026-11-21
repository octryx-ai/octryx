// The "⋯" menu of an assistant message: the message itself shows only Copy and Retry; Prompt
// (retry the preceding prompt), Read aloud, and the diagnostics Think, Perf and Trace move into this menu. Nothing
// is removed: every entry calls the same handler the separate buttons called before.
export type MessageMenuItem = {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  checked?: boolean;
};

export type MessageMenuInput = {
  retryPrompt?: string | null;
  retrying: boolean;
  actionsDisabled: boolean;
  triggerRetryPrompt: () => Promise<void>;
  speaking: boolean;
  toggleSpeak: () => void;
  hasTurnTrace: boolean;
  thinkingOpen: boolean;
  thinkingLoading: boolean;
  toggleThinking: () => Promise<void>;
  performanceOpen: boolean;
  performanceLoading: boolean;
  togglePerformance: () => Promise<void>;
  traceLoading: boolean;
  openTrace: () => Promise<void>;
};

/** The entries of an assistant message's "⋯" menu, in a fixed order; diagnostics only when the turn has a trace. */
export function assistantMessageMenuItems(input: MessageMenuInput): MessageMenuItem[] {
  const items: MessageMenuItem[] = [];
  if (input.retryPrompt) {
    items.push({
      label: input.retrying ? "Retrying…" : "Retry the preceding prompt",
      disabled: input.actionsDisabled || input.retrying,
      onSelect: () => void input.triggerRetryPrompt(),
    });
  }
  items.push({ label: input.speaking ? "Stop reading" : "Read aloud", onSelect: input.toggleSpeak });
  if (input.hasTurnTrace) {
    items.push(
      {
        label: input.thinkingLoading ? "Loading thinking…" : "Thinking details",
        disabled: input.thinkingLoading,
        checked: input.thinkingOpen,
        onSelect: () => void input.toggleThinking(),
      },
      {
        label: input.performanceLoading ? "Loading performance…" : "Performance details",
        disabled: input.performanceLoading,
        checked: input.performanceOpen,
        onSelect: () => void input.togglePerformance(),
      },
      {
        label: input.traceLoading ? "Loading trace…" : "Open trace",
        disabled: input.traceLoading,
        onSelect: () => void input.openTrace(),
      },
    );
  }
  return items;
}
