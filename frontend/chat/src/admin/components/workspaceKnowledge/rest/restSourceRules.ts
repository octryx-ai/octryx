// Custom REST source: who may choose "workspace", the API catalog, detail operations, problems and the request body.
import { pathProblem, roleRule } from "../../../../chat/work/intake/restIntakeModel";
import type { Pair, RestOperationInfo } from "../../../../chat/work/intake/restIntakeForm";
import { MAPPING_FIELDS, MEDIA_JSON, type RestKnowledgeForm } from "./restSourceForm";
import { record, str } from "./restSourceValues";

// ---- visibility ---------------------------------------------------------------------------------------------------

export const RESTRICTED_TEXT = "People only find what their roles' grants allow.";
export const WORKSPACE_TEXT = "Everyone in the Workspace finds every item, whatever their grants.";
export const WORKSPACE_ADMIN_ONLY = "Only a platform admin can make a REST source visible to the whole Workspace.";

/** Whether this person may choose "workspace", and the hint shown when not. The server refuses it the same way (403). */
export function visibilityRule(isPlatformAdmin: boolean): { workspaceAllowed: boolean; hint: string | null } {
  return isPlatformAdmin ? { workspaceAllowed: true, hint: null } : { workspaceAllowed: false, hint: WORKSPACE_ADMIN_ONLY };
}

// ---- catalog ------------------------------------------------------------------------------------------------------

// One REST API a source may read (`GET …/knowledge/rest-sources`): its key (what `scope.definition` stores), its
// name, and its enabled read operations. A platform admin also sees APIs without a connection here and operations
// without a grant here; they are offered with a note, and the save names the missing piece at its field.
export type RestApiChoice = { id: string; name: string; connected: boolean; operations: RestOperationInfo[] };

const strings = (value: unknown) => (Array.isArray(value) ? value.map(str).filter(Boolean) : []);

export function restCatalogOf(answer: unknown): RestApiChoice[] {
  const definitions = record(answer).definitions;
  if (!Array.isArray(definitions)) return [];
  return definitions.map(record).filter((entry) => str(entry.key)).map((entry) => ({
    id: str(entry.key),
    name: str(entry.name) || str(entry.key),
    connected: entry.connection !== null && entry.connection !== undefined,
    operations: (Array.isArray(entry.operations) ? entry.operations : []).map(record).filter((op) => str(op.op_key)).map((op) => ({
      op_key: str(op.op_key), name: str(op.name) || str(op.op_key), method: str(op.method), path: str(op.path),
      summary: typeof op.summary === "string" ? op.summary : null, paginated: op.paginated === true,
      roles: strings(op.roles), scoped_roles: strings(op.scoped_roles), role_required: op.role_required === true,
    })),
  }));
}

// ---- detail operation ---------------------------------------------------------------------------------------------

/** The `{name}` parameters of an operation path: the record's id goes into one of them. */
export function pathParams(path: string | undefined): string[] {
  return Array.from((path ?? "").matchAll(/\{([^{}]+)\}/g), (match) => match[1].trim()).filter(Boolean);
}

/** The read operations a detail may use: enabled reads with a path parameter, never the list operation itself. */
export function detailCandidates(operations: RestOperationInfo[], listOperation: string): RestOperationInfo[] {
  return operations.filter((operation) => operation.op_key !== listOperation && pathParams(operation.path).length > 0);
}

// ---- problems -----------------------------------------------------------------------------------------------------

/** What blocks a save or dry run, per server field name (`scope.role`, `mapping.title` ...). Empty when none. */
export function restKnowledgeProblems(form: RestKnowledgeForm, operations: RestOperationInfo[], isPlatformAdmin: boolean): Record<string, string> {
  const problems: Record<string, string> = {};
  if (!form.definition) problems["scope.definition"] = "Pick the REST API.";
  const operation = operations.find((entry) => entry.op_key === form.operation);
  if (!form.operation) problems["scope.operation"] = "Pick the list operation.";
  const role = roleRule(operation, form.role).problem;
  if (role) problems["scope.role"] = role;
  if (form.contentFrom === "detail") {
    const detail = operations.find((entry) => entry.op_key === form.detailOperation);
    if (!form.detailOperation) problems["scope.detail_operation"] = "Pick the read operation that returns one record.";
    else if (detail && pathParams(detail.path).length !== 1 && !form.detailParam) {
      problems["scope.detail_param"] = "Pick the argument that takes the record's id.";
    }
  }
  for (const { name, label } of MAPPING_FIELDS) {
    const problem = pathProblem(form.mapping[name]);
    if (problem) problems[`mapping.${name}`] = `${label.replace(" *", "")}: ${problem}`;
  }
  if (!problems["mapping.title"] && !form.mapping.title.trim()) problems["mapping.title"] = "Map the title: every item needs one.";
  if (!problems["mapping.id"] && !form.mapping.id.trim()) problems["mapping.id"] = "Map the id: it identifies the item across syncs.";
  if (!form.mapping.updated_at.trim() && !form.mapping.version.trim() && !problems["mapping.updated_at"]) {
    problems["mapping.updated_at"] = "Map Updated or Version: a sync re-reads only records that changed.";
  }
  const content = form.contentPath.trim();
  if (form.contentFrom !== "record") {
    const problem = pathProblem(content);
    if (problem) problems["mapping.content"] = problem;
    else if (!content && (form.contentFrom === "field" || form.mediaType !== MEDIA_JSON)) {
      problems["mapping.content"] = "Name the field that holds the text.";
    }
  }
  if (form.visibility === "workspace" && !isPlatformAdmin) problems["scope.visibility"] = WORKSPACE_ADMIN_ONLY;
  return problems;
}

/** The dot-path problems of what is typed so far: shown while typing, before any save is tried. */
export function livePathProblems(form: RestKnowledgeForm): Record<string, string> {
  const problems: Record<string, string> = {};
  for (const { name, label } of MAPPING_FIELDS) {
    const problem = pathProblem(form.mapping[name]);
    if (problem) problems[`mapping.${name}`] = `${label.replace(" *", "")}: ${problem}`;
  }
  const content = form.contentFrom === "record" ? null : pathProblem(form.contentPath);
  if (content) problems["mapping.content"] = content;
  return problems;
}

// ---- request body -------------------------------------------------------------------------------------------------

const pairObject = (entries: Pair[]) =>
  Object.fromEntries(entries.filter((entry) => entry.name.trim()).map((entry) => [entry.name.trim(), entry.value]));

/** The `scope` and `mapping` objects the server validates (`PUT` and `POST …/sample` take the same). */
export function restKnowledgeBody(form: RestKnowledgeForm): { scope: Record<string, unknown>; mapping: Record<string, string> } {
  const mapping: Record<string, string> = {};
  for (const { name } of MAPPING_FIELDS) {
    const path = form.mapping[name].trim();
    if (path) mapping[name] = path;
  }
  const content = form.contentPath.trim();
  if (form.contentFrom !== "record" && content) mapping.content = content;
  const detail = form.contentFrom === "detail";
  const since = form.updatedSinceParam.trim();
  return {
    scope: {
      definition: form.definition,
      operation: form.operation,
      role: form.role.trim() || null,
      arguments: pairObject(form.arguments),
      ...(detail ? { detail_operation: form.detailOperation, ...(form.detailParam ? { detail_param: form.detailParam } : {}) } : {}),
      ...(since ? { updated_since_param: since } : {}),
      media_type: form.contentFrom === "record" ? MEDIA_JSON : form.mediaType,
      visibility: form.visibility,
    },
    mapping,
  };
}

/** A stored source's configuration for a re-save (pause/resume): its scope without the mapping, and the mapping. */
export function storedRestBody(scope: unknown): { scope: Record<string, unknown>; mapping: Record<string, unknown> } {
  const { mapping, ...rest } = record(scope);
  return { scope: rest, mapping: record(mapping) };
}
