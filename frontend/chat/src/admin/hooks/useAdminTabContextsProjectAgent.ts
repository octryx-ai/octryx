export function buildAgentsTabCtx(
  params: Record<string, unknown> & {
    agentForms?: Record<string, unknown>;
    agentState?: Record<string, unknown>;
    onClose: () => void;
    projects?: unknown;
  },
): Record<string, unknown> {
  const agentForms =
    params.agentForms && typeof params.agentForms === "object"
      ? params.agentForms
      : params;
  const agentState =
    params.agentState && typeof params.agentState === "object"
      ? params.agentState
      : params;
  const projects =
    params.projects ??
    (agentState as Record<string, unknown>).adminProjects ??
    [];
  const { onClose } = params;
  return {
    ...agentForms,
    ...agentState,
    onClose,
    projects,
    readJson: params.readJson,
  };
}

export function buildProjectsTabCtx(
  params: Record<string, unknown> & {
    projectQualityCore?: Record<string, unknown>;
    projectDesignTrace?: Record<string, unknown>;
    projectState?: Record<string, unknown>;
    projects?: unknown;
  },
): Record<string, unknown> {
  const projectQualityCore =
    params.projectQualityCore && typeof params.projectQualityCore === "object"
      ? params.projectQualityCore
      : params;
  const projectDesignTrace =
    params.projectDesignTrace && typeof params.projectDesignTrace === "object"
      ? params.projectDesignTrace
      : params;
  const projectState =
    params.projectState && typeof params.projectState === "object"
      ? params.projectState
      : params;
  const projects = params.projects ?? [];
  return {
    ...projectQualityCore,
    ...projectDesignTrace,
    ...projectState,
    projects,
  };
}
