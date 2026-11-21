// Connector limit codec: limit field values to editable text lines and back.

const OBJECT_LIST_LIMIT_FIELDS: Record<string, string> = {
  jenkins_allowed_jobs: "job_name",
  nexus_allowed_repositories: "repository",
};

function stringifyList(
  value: unknown,
  formatter: (item: unknown) => string,
): string {
  if (!Array.isArray(value)) return "";
  return value.map(formatter).filter(Boolean).join("\n");
}

export function stringifyStrings(value: unknown): string {
  return stringifyList(value, (item) => (typeof item === "string" ? item : ""));
}

export function stringifySpaces(value: unknown): string {
  return stringifyList(value, (item) => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    const entry = item as Record<string, unknown>;
    return String(entry.space_key || entry.key || "").trim();
  });
}

export function stringifyPages(value: unknown): string {
  return stringifyList(value, (item) => {
    if (!item || typeof item !== "object") return "";
    const entry = item as Record<string, unknown>;
    if (entry.whole_space === true) return "";
    const id = String(entry.id || "").trim();
    const title = String(entry.title || "").trim();
    const space = String(entry.space_key || "").trim();
    return [id, title, space].filter(Boolean).join(" | ");
  });
}

export function stringifyRepos(value: unknown): string {
  return stringifyList(value, (item) => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    const entry = item as Record<string, unknown>;
    const projectKey = String(entry.project_key || entry.project || "").trim();
    const repoSlug = String(entry.repo_slug || entry.slug || "").trim();
    return projectKey && repoSlug ? `${projectKey}/${repoSlug}` : "";
  });
}

function stringifyObjectList(value: unknown, key: string): string {
  return stringifyList(value, (item) => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    const entry = item as Record<string, unknown>;
    return String(entry[key] || "").trim();
  });
}

export function stringifyLimitField(fieldName: string, value: unknown): string {
  if (fieldName === "jira_allowed_projects") return stringifyStrings(value);
  if (fieldName === "confluence_allowed_spaces") return stringifySpaces(value);
  if (fieldName === "confluence_allowed_pages") return stringifyPages(value);
  if (fieldName === "bitbucket_allowed_repos") return stringifyRepos(value);
  const objectKey = OBJECT_LIST_LIMIT_FIELDS[fieldName];
  if (objectKey) return stringifyObjectList(value, objectKey);
  return stringifyStrings(value);
}

export function splitLines(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseSpaces(
  value: string,
): Array<{ space_key: string; enabled: boolean }> {
  return splitLines(value).map((spaceKey) => ({
    space_key: spaceKey,
    enabled: true,
  }));
}

export function parsePages(value: string): Array<Record<string, unknown>> {
  return splitLines(value).map((line) => {
    const [id = "", title = "", spaceKey = ""] = line
      .split("|")
      .map((part) => part.trim());
    return {
      id,
      title,
      space_key: spaceKey,
      enabled: true,
      include_children: false,
    };
  });
}

function parseRepos(
  value: string,
): Array<{ project_key: string; repo_slug: string; enabled: boolean }> {
  return splitLines(value)
    .map((line) => {
      const [projectKey = "", repoSlug = ""] = line
        .split("/")
        .map((part) => part.trim());
      return projectKey && repoSlug
        ? { project_key: projectKey, repo_slug: repoSlug, enabled: true }
        : null;
    })
    .filter(
      (
        item,
      ): item is {
        project_key: string;
        repo_slug: string;
        enabled: boolean;
      } => Boolean(item),
    );
}

function parseObjectList(
  value: string,
  key: string,
): Array<Record<string, unknown>> {
  return splitLines(value).map((item) => ({
    [key]: item,
    enabled: true,
  }));
}

export function parseLimitField(fieldName: string, value: string): unknown[] {
  if (fieldName === "jira_allowed_projects") {
    return splitLines(value).map((item) => item.toUpperCase());
  }
  if (fieldName === "confluence_allowed_spaces") return parseSpaces(value);
  if (fieldName === "confluence_allowed_pages") return parsePages(value);
  if (fieldName === "bitbucket_allowed_repos") return parseRepos(value);
  const objectKey = OBJECT_LIST_LIMIT_FIELDS[fieldName];
  if (objectKey) return parseObjectList(value, objectKey);
  return splitLines(value);
}
