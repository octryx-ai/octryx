import { useAdminNavigation } from "../../adminNavigation";
import type { AdminTab } from "../../types/adminPanelTypes.governance";
import "./areaPurpose.css";

export type AreaPurposeLink = { tab: AdminTab; label: string };

type Props = {
  links?: AreaPurposeLink[];
  // The page this one belongs to (e.g. Workflows for Scenarios): shown as a way back.
  back?: AreaPurposeLink;
};

// The way back and links to the related pages, shown under the shell's page title. The page's purpose and "when to
// use" are in the page's help (help/<area>/<page>.md), not on the page.
export function AreaPurpose({ links = [], back }: Props) {
  const { openAdminTab } = useAdminNavigation();
  if (!back && !links.length) return null;
  return (
    <div className="area-purpose">
      {back ? (
        <button type="button" className="admin-panel__action-btn area-purpose__back" onClick={() => openAdminTab(back.tab)}>
          ← {back.label}
        </button>
      ) : null}
      {links.length ? (
        <nav className="area-purpose__links" aria-label="Related pages">
          <span className="area-purpose__label">Related</span>
          {links.map((link) => (
            <button key={link.tab} type="button" className="area-purpose__link" onClick={() => openAdminTab(link.tab)}>
              {link.label}
            </button>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
