import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { MCP_ALLOW_API, readStatus } from "./mcpAllowContract";
import type { ServerStatus } from "./mcpAllowContract";

/** The status pipeline of every registration; ``reload`` after a connect, an edit or an allow. */
export function useMcpAllowStatus(refreshKey: unknown) {
  const [status, setStatus] = useState<Map<string, ServerStatus>>(new Map());
  const reload = useCallback(() => {
    readJson<unknown>(`${MCP_ALLOW_API}/mcp-servers/allow`).then((payload) => setStatus(readStatus(payload)))
      .catch(() => setStatus(new Map()));
  }, []);
  useEffect(reload, [reload, refreshKey]);
  return { status, reload };
}
