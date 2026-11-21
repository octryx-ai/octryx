import { useCallback, useEffect, useState } from "react";

import { DataTable } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { ToolSetPanel } from "./ToolSetPanel";
import { listFunctions, listRoles } from "./workRolesApi";
import { errorView, type ErrorView } from "./workRolesModel";
import { Card, ErrorLine } from "./WorkRolesParts";
import type { WorkFunction, WorkRole } from "./workRolesTypes";
import "./workRoles.css";

// Admin › People & sign-in › Roles & functions › Functions: what each function lets a person do and its tool set.
export function WorkFunctionsPage({ isAdmin }: { isAdmin: boolean }) {
  const [functions, setFunctions] = useState<WorkFunction[] | null>(null);
  const [roles, setRoles] = useState<WorkRole[]>([]);
  const [error, setError] = useState<ErrorView | null>(null);
  const [open, setOpen] = useState<WorkFunction | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextFunctions, nextRoles] = await Promise.all([listFunctions(), listRoles()]);
      setFunctions(nextFunctions);
      setRoles(nextRoles);
      setError(null);
    } catch (failure) {
      setFunctions([]);
      setError(errorView(failure, "The functions could not be loaded."));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const roleNames = (fn: WorkFunction) =>
    roles.filter((role) => role.function_keys.includes(fn.key) || fn.role_keys.includes(role.key)).map((role) => role.name);

  return (
    <div className="wr-page" data-testid="work-functions-page">
      <ErrorLine error={error} />
      <Card title="Functions" testId="function-list"
        meta="The platform brings the functions; each carries the tools a person with it may use. With Role-based tools on, a person gets the tools of all functions of their roles.">
        <DataTable<WorkFunction>
          label="Functions" rows={functions ?? []} loading={functions === null} rowKey={(fn) => fn.id}
          onOpen={setOpen} selectedKey={open?.id ?? null}
          columns={[
            { key: "name", header: "Function", grow: true, minWidth: "18rem", render: (fn) => (
              <span className="wr-name">
                <span className="wr-name__line"><span className="wr-name__title">{fn.name}</span>
                  <StatusLabel label={fn.built_in ? "Built-in" : "Custom"} tone="neutral" /></span>
                <span className="wr-name__sub">{fn.description}</span>
              </span>
            ) },
            { key: "tools", header: "Tool set", nowrap: true, render: (fn) => `${fn.tools.length} ${fn.tools.length === 1 ? "entry" : "entries"}` },
            { key: "roles", header: "In roles", clip: "22rem", render: (fn) => {
              const names = roleNames(fn);
              return <span title={names.join(", ")} className={names.length ? undefined : "wr-muted"}>{names.length ? names.join(", ") : "No role"}</span>;
            } },
          ]}
        />
      </Card>
      {open ? (
        <ToolSetPanel key={open.id} fn={open} roleNames={roleNames(open)} canEdit={isAdmin}
          onClose={() => setOpen(null)} onSaved={() => void load()} />
      ) : null}
    </div>
  );
}
