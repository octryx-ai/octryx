import { readJson } from "../../utils/adminPanelHelpers";
import { readContentCategories } from "../providerTab/litellmGatewayApprovedCategories";
import type { ContentCategory } from "../providerTab/litellmGatewayApprovedCategories";

// The content categories the policy engine knows (built-in + admin categories of the working set): the
// choices of a catalog model's "Approved for". Loaded once per page view.

const CATEGORIES_PATH = "/api/v1/admin/policy-engine/content-detectors";
let request: Promise<ContentCategory[]> | null = null;

export function loadContentCategories(): Promise<ContentCategory[]> {
  request ??= readJson<unknown>(CATEGORIES_PATH)
    .then(readContentCategories)
    .catch((error) => {
      request = null;
      throw error;
    });
  return request;
}

export const categoryLabel = (categories: ContentCategory[], id: string): string =>
  categories.find((item) => item.id === id)?.label || id;
