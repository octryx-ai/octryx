// Structured Engineering Knowledge Pack build request for the admin builder.
// The backend builds a pack only from these exact version coordinates
// (services/engineering_knowledge/pack_build_request.py); no prompt text is
// parsed for versions.

export const ENGINEERING_KNOWLEDGE_COORDINATES = [
  { key: "java", label: "Java" },
  { key: "spring_boot", label: "Spring Boot" },
  { key: "python", label: "Python" },
] as const;

export type EngineeringKnowledgeCoordinate =
  (typeof ENGINEERING_KNOWLEDGE_COORDINATES)[number]["key"];

export type EngineeringKnowledgeBuildVersions = Record<
  EngineeringKnowledgeCoordinate,
  { source: string; target: string }
>;

export const DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS: EngineeringKnowledgeBuildVersions =
  {
    java: { source: "21", target: "25" },
    spring_boot: { source: "3.4", target: "4.0.3" },
    python: { source: "", target: "" },
  };

export function engineeringKnowledgeBuildPayload(
  versions: EngineeringKnowledgeBuildVersions,
): {
  source_versions: Record<string, string>;
  target_versions: Record<string, string>;
} {
  const source_versions: Record<string, string> = {};
  const target_versions: Record<string, string> = {};
  for (const { key } of ENGINEERING_KNOWLEDGE_COORDINATES) {
    const source = versions[key].source.trim();
    const target = versions[key].target.trim();
    if (source) {
      source_versions[key] = source;
    }
    if (target) {
      target_versions[key] = target;
    }
  }
  return { source_versions, target_versions };
}

export function hasEngineeringKnowledgeTargetVersion(
  versions: EngineeringKnowledgeBuildVersions,
): boolean {
  return (
    Object.keys(engineeringKnowledgeBuildPayload(versions).target_versions)
      .length > 0
  );
}
