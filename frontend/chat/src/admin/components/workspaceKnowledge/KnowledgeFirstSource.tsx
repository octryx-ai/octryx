import { useAdminNavigation } from "../../adminNavigation";

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
