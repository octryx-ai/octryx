import { useAdminNavigation } from "../../adminNavigation";
import { workflowAdministrationPages } from "./workflowAdministration";
import "./areaPurpose.css";

// Collapsed by default under the workflow list: the related administration pages with what each
// one is for and a way to open it. Every page keeps its own authorization.
export function WorkflowAdministrationSection() {
  const { openAdminTab } = useAdminNavigation();
  const pages = workflowAdministrationPages();
  return (
    <details className="area-disclosure" data-testid="workflow-administration">
      <summary className="area-disclosure__summary">Advanced workflow administration</summary>
      <div className="area-disclosure__body">
        <p className="admin-panel__hint">Manage scenarios.</p>
        <table className="admin-panel__table">
          <thead>
            <tr>
              <th>Page</th>
              <th>What it is for</th>
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {pages.map((page) => (
              <tr key={page.tab}>
                <td>{page.title}</td>
                <td>{page.purpose}</td>
                <td>
                  <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab(page.tab)}>
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
