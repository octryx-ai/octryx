import { createElement } from "react";
import { areaWithWorkspace, useActiveWorkspaceName } from "./activeWorkspaceName";

// A .ts module with createElement so the unit-test loaders can load it.
export function AreaTitle({ area, className }: { area: string; className: string }) {
  const name = useActiveWorkspaceName();
  return createElement("div", { className, title: areaWithWorkspace(area, name), "data-testid": "area-title" },
    areaWithWorkspace(area, name));
}
