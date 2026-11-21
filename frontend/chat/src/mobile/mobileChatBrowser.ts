// Browser helpers of the mobile chat pages: colour theme, text selection and clipboard.

export const theme = (): "dark" | "light" =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";

// While the person selects text, the chat does not re-render under their finger (the poll would clear the selection).
export const selecting = () => {
  try {
    return Boolean(window.getSelection()?.toString());
  } catch {
    return false;
  }
};

export function copy(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}
