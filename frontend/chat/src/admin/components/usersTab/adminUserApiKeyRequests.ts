// The requests behind a user's API key dialog: list, create and revoke, each writing its result into the dialog state.
import type { Dispatch, SetStateAction } from "react";

import type {
  AdminReadJsonFn,
  AdminUserApiKeyCreateResponse,
  AdminUserApiKeyRow,
  AdminUserRow,
} from "./identityTypes";

export type ApiKeyState = {
  setApiKeys: Dispatch<SetStateAction<AdminUserApiKeyRow[]>>;
  setApiKeyCreatedSecret: Dispatch<SetStateAction<string | null>>;
  setApiKeyLoading: Dispatch<SetStateAction<string | null>>;
  setApiKeyError: Dispatch<SetStateAction<string | null>>;
};

export type ApiKeyDraft = {
  name: string;
  scopes: string;
  expiresAt: string;
  clear: () => void;
};

export async function listUserApiKeys(
  readJson: AdminReadJsonFn,
  user: AdminUserRow,
  state: ApiKeyState,
) {
  state.setApiKeyLoading(`list:${user.id}`);
  state.setApiKeyCreatedSecret(null);
  try {
    const data = await readJson<AdminUserApiKeyRow[]>(
      `/admin/chat/api/panel/users/${user.id}/api-keys`,
    );
    state.setApiKeys(Array.isArray(data) ? data : []);
    state.setApiKeyError(null);
  } catch (error) {
    state.setApiKeyError(
      error instanceof Error ? error.message : "Failed to load API keys",
    );
  } finally {
    state.setApiKeyLoading(null);
  }
}

export async function createUserApiKey(
  readJson: AdminReadJsonFn,
  user: AdminUserRow,
  draft: ApiKeyDraft,
  state: ApiKeyState,
) {
  state.setApiKeyLoading(`create:${user.id}`);
  state.setApiKeyCreatedSecret(null);
  try {
    const payload = await readJson<AdminUserApiKeyCreateResponse>(
      `/admin/chat/api/panel/users/${user.id}/api-keys`,
      {
        method: "POST",
        body: JSON.stringify({
          name: draft.name,
          scopes: draft.scopes
            .split(",")
            .map((scope) => scope.trim())
            .filter(Boolean),
          expires_at: draft.expiresAt
            ? new Date(draft.expiresAt).toISOString()
            : null,
        }),
      },
    );
    const { api_key: apiKey, ...row } = payload;
    state.setApiKeys((current) => [row, ...current]);
    state.setApiKeyCreatedSecret(apiKey);
    draft.clear();
    state.setApiKeyError(null);
  } catch (error) {
    state.setApiKeyError(
      error instanceof Error ? error.message : "Failed to create API key",
    );
  } finally {
    state.setApiKeyLoading(null);
  }
}

export async function revokeUserApiKey(
  readJson: AdminReadJsonFn,
  user: AdminUserRow,
  key: AdminUserApiKeyRow,
  state: ApiKeyState,
) {
  state.setApiKeyLoading(`revoke:${key.id}`);
  try {
    const revoked = await readJson<AdminUserApiKeyRow>(
      `/admin/chat/api/panel/users/${user.id}/api-keys/${key.id}`,
      { method: "DELETE" },
    );
    state.setApiKeys((current) =>
      current.map((item) => (item.id === key.id ? revoked : item)),
    );
    state.setApiKeyError(null);
  } catch (error) {
    state.setApiKeyError(
      error instanceof Error ? error.message : "Failed to revoke API key",
    );
  } finally {
    state.setApiKeyLoading(null);
  }
}
