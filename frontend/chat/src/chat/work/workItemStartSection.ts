// The start form's anchor in the Work Item detail and the scroll to it after "Start workflow".
export const START_SECTION_ID = "work-detail-start";

// Start workflow opens the start form on Overview (it keeps its Advanced run limits); Cancel puts it away again.
export function scrollToStartSection() {
  setTimeout(() => {
    if (typeof document === "undefined") return;
    document.getElementById(START_SECTION_ID)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, 0);
}
