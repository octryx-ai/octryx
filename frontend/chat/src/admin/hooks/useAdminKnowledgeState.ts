import { useState } from "react";

// The knowledge tab's state: its project selection (entity graph).
export function useAdminKnowledgeState() {
  const [knowledgeProjectId, setKnowledgeProjectId] = useState("");

  return {
    knowledgeProjectId,
    setKnowledgeProjectId,
  };
}
