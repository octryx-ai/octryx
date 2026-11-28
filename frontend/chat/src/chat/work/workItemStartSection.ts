export const START_SECTION_ID = "work-detail-start";

export function scrollToStartSection() {
  setTimeout(() => {
    if (typeof document === "undefined") return;
    document.getElementById(START_SECTION_ID)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, 0);
}
