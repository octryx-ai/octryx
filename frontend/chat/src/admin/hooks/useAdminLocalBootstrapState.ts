import { useState } from "react";
import type { LocalBootstrapStatus, SetupGuideStatus } from "../types/adminPanelTypes.usersProviders";

export function useAdminLocalBootstrapState() {
  const [localBootstrap, setLocalBootstrap] =
    useState<LocalBootstrapStatus | null>(null);
  const [setupGuide, setSetupGuide] = useState<SetupGuideStatus | null>(null);
  const [localBootstrapLoading, setLocalBootstrapLoading] = useState(false);
  const [localBootstrapActionLoading, setLocalBootstrapActionLoading] =
    useState<string | null>(null);
  const [localBootstrapError, setLocalBootstrapError] = useState<string | null>(
    null,
  );
  const [localBootstrapEndpointDraft, setLocalBootstrapEndpointDraft] =
    useState("http://localhost:11434");
  const [localBootstrapModelDraft, setLocalBootstrapModelDraft] =
    useState("gemma4");
  const [localBootstrapDisplayDraft, setLocalBootstrapDisplayDraft] = useState(
    "Local Gemma 4 Anchor",
  );
  const [localBootstrapPullModel, setLocalBootstrapPullModel] = useState(true);
  const [localBootstrapMakePrimary, setLocalBootstrapMakePrimary] =
    useState(true);

  return {
    localBootstrap,
    setLocalBootstrap,
    setupGuide,
    setSetupGuide,
    localBootstrapLoading,
    setLocalBootstrapLoading,
    localBootstrapActionLoading,
    setLocalBootstrapActionLoading,
    localBootstrapError,
    setLocalBootstrapError,
    localBootstrapEndpointDraft,
    setLocalBootstrapEndpointDraft,
    localBootstrapModelDraft,
    setLocalBootstrapModelDraft,
    localBootstrapDisplayDraft,
    setLocalBootstrapDisplayDraft,
    localBootstrapPullModel,
    setLocalBootstrapPullModel,
    localBootstrapMakePrimary,
    setLocalBootstrapMakePrimary,
  };
}
