import { useAdminNavigation } from "../../adminNavigation";
import { openPolicies } from "./policyLinks";
import { usePolicyReferences } from "./usePolicyReferences";
import "./policiesPage.css";

// On a named connection: "Policies affecting this connection (N)" opens the policy list filtered
// by that connection; on the default entry, "Connector-wide policies (N)" filters by the connector. Platform admins
// only: for anyone else nothing is shown.
export function ConnectionPolicies({ connector, connectionId = null }: { connector: string; connectionId?: string | null }) {
  const { openAdminTab } = useAdminNavigation();
  const references = usePolicyReferences();
  if (!references) return null;
  const count = connectionId ? references.connections[connectionId]?.count ?? 0 : references.connectorWide[connector]?.count ?? 0;
  if (!count) return <span className="policies__src" data-testid="connection-policies-none">No policies</span>;
  return (
    <button type="button" className={`admin-policy-chip${connectionId ? "" : " admin-policy-chip--secondary"}`} data-testid="connection-policies"
      onClick={() => openPolicies(openAdminTab, connectionId ? { connection: connectionId } : { connector })}>
      {connectionId ? `Policies affecting this connection (${count})` : `Connector-wide policies (${count})`}
    </button>
  );
}
