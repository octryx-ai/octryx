export const CODING_NAV_ITEMS = [
  { key: "sessions", label: "Sessions", section: "Code work", purpose: "Coding sessions, from plan to review." },
  { key: "repositories", label: "Repositories", section: "Code work", purpose: "Every repository the Workspace uses: its source, branch, coding setup and runs." },
  { key: "pipelines", label: "Delivery pipeline", section: "Delivery", purpose: "The steps and checks every coding session runs." },
  { key: "rules", label: "Effective rules", section: "Governance", purpose: "Everything that limits the coding agent in this Workspace." },
] as const;

export type CodingNavKey = (typeof CODING_NAV_ITEMS)[number]["key"];

export const DELIVERY_PIPELINE_VIEW = "delivery_pipeline";

export function codingViewParam(key: CodingNavKey): string {
  return key === "pipelines" ? DELIVERY_PIPELINE_VIEW : key;
}

export function codingNavFromSearch(search: string): CodingNavKey {
  const view = new URLSearchParams(search).get("coding_view");
  return CODING_NAV_ITEMS.find((item) => codingViewParam(item.key) === view)?.key ?? "sessions";
}

export function CodingNavIcon({ navKey }: { navKey: CodingNavKey }) {
  const paths: Record<CodingNavKey, string[]> = {
    sessions: ["M5 4h10v12H5z", "M7 7h6", "M7 10h4"],
    repositories: ["M5 3h8l2 2v12H5z", "M8 8l-2 2 2 2", "M12 8l2 2-2 2"],
    pipelines: ["M4 5h4v4H4z", "M12 5h4v4h-4z", "M4 13h4v4H4z", "M8 7h4", "M8 15h4", "M14 9v4"],
    rules: ["M10 3l6 2.5v4.5c0 3.4-2.5 6.2-6 7-3.5-.8-6-3.6-6-7V5.5z", "M7.5 10l1.8 1.8L13 8"],
  };
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      {paths[navKey].map((path) => (
        <path key={path} d={path} />
      ))}
    </svg>
  );
}
