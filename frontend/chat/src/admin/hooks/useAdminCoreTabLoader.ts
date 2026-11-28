import type { Dispatch, SetStateAction } from "react";
import type { AdminProvider, AdminToolCatalogEntry, AdminUser } from "../types/adminPanelTypes.usersProviders";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import {
  DEFAULT_PAGINATION_LIMIT,
  resolvePaginationLimit,
  resolvePaginationOffset,
} from "../utils/adminPagination";
import { isObjectRecord } from "../utils/adminPanelHelpers";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type Paginated<T> = {
  items: T[];
  total: number;
};

function normalizePaginatedPayload<T>(
  payload: unknown,
  totalFallback = 0,
): Paginated<T> {
  if (!isObjectRecord(payload)) {
    return { items: [], total: totalFallback };
  }

  const items = Array.isArray((payload as { items?: unknown }).items)
    ? ((payload as { items?: T[] }).items ?? [])
    : [];

  const totalValue = (payload as { total?: unknown }).total;
  const total = Number.isFinite(typeof totalValue === "number" ? totalValue : Number(totalValue))
    ? Number(totalValue)
    : totalFallback;

  return { items, total };
}

type LoadProvidersTabDataArgs = {
  readJson: ReadJsonFn;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
};

export async function loadProvidersTabData({
  readJson,
  setProviders,
}: LoadProvidersTabDataArgs) {
  const providerData = await readJson<AdminProvider[]>(
    "/admin/chat/api/panel/providers",
  );
  setProviders(providerData);
}

export async function loadUsersTabData(
  readJson: ReadJsonFn,
  setUsers: Dispatch<SetStateAction<AdminUser[]>>,
) {
  const data = await readJson<AdminUser[]>("/admin/chat/api/panel/users");
  setUsers(data);
}

export async function loadProjectsTabData(
  readJson: ReadJsonFn,
  setAdminProjects: Dispatch<SetStateAction<AdminProjectQuality[]>>,
) {
  const data = await readJson<AdminProjectQuality[]>(
    "/admin/chat/api/panel/projects",
  );
  setAdminProjects(data);
}

export async function loadToolCatalogTabData(
  readJson: ReadJsonFn,
  setToolCatalog: Dispatch<SetStateAction<AdminToolCatalogEntry[]>>,
) {
  const data = await readJson<AdminToolCatalogEntry[]>(
    "/admin/chat/api/panel/tool-catalog",
  );
  setToolCatalog(data);
}

