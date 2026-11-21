import { useAdminNavigation } from "../../adminNavigation";

// The first source of a Workspace: a source reads through a connection to its system, so the
// add panel says in one line where that connection is made.
export function KnowledgeFirstSource() {
  const { openAdminTab } = useAdminNavigation();
  return (
    <p className="knowledge-sources__notice" data-testid="knowledge-first-source">
      Sources read through a connection, set up in{" "}
      <a href="/chat?area=admin&tab=adminConnections"
        onClick={(event) => { event.preventDefault(); openAdminTab("adminConnections"); }}>Admin › Connections</a>.
    </p>
  );
}
