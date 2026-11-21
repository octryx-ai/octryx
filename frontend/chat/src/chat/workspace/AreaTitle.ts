import { createElement } from "react";
import { areaWithWorkspace, useActiveWorkspaceName } from "./activeWorkspaceName";

// The title in an area's sidebar head with the active Workspace written out: "Work · Test".
// A .ts module with createElement so the unit-test loaders can load it like the other shared layout blocks.
export function AreaTitle({ area, className }: { area: string; className: string }) {
  const name = useActiveWorkspaceName();
  return createElement("div", { className, title: areaWithWorkspace(area, name), "data-testid": "area-title" },
    areaWithWorkspace(area, name));
}
