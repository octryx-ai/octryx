import { useCallback, useState, type FormEvent } from "react";

import { createUserApiKey, listUserApiKeys, revokeUserApiKey } from "./adminUserApiKeyRequests";
import type { AdminReadJsonFn, AdminUserApiKeyRow, AdminUserRow } from "./identityTypes";

export function useAdminUserApiKeys(readJson: AdminReadJsonFn) {
  const [apiKeyUser, setApiKeyUser] = useState<AdminUserRow | null>(null);
  const [apiKeys, setApiKeys] = useState<AdminUserApiKeyRow[]>([]);
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeyScopes, setApiKeyScopes] = useState("");
  const [apiKeyExpiresAt, setApiKeyExpiresAt] = useState("");
  const [apiKeyCreatedSecret, setApiKeyCreatedSecret] = useState<string | null>(
    null,
  );
  const [apiKeyLoading, setApiKeyLoading] = useState<string | null>(null);
  const [apiKeyError, setApiKeyError] = useState<string | null>(null);

  const loadUserApiKeys = useCallback(
    async (user: AdminUserRow) => {
      setApiKeyUser(user);
      await listUserApiKeys(readJson, user, { setApiKeys, setApiKeyCreatedSecret, setApiKeyLoading, setApiKeyError });
    },
    [readJson],
  );

  const closeApiKeyDialog = useCallback(() => {
    setApiKeyUser(null);
    setApiKeys([]);
    setApiKeyName("");
    setApiKeyScopes("");
    setApiKeyExpiresAt("");
    setApiKeyCreatedSecret(null);
    setApiKeyError(null);
  }, []);

  const createApiKey = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!apiKeyUser) return;
      const clear = () => { setApiKeyName(""); setApiKeyScopes(""); setApiKeyExpiresAt(""); };
      await createUserApiKey(readJson, apiKeyUser, { name: apiKeyName, scopes: apiKeyScopes, expiresAt: apiKeyExpiresAt, clear },
        { setApiKeys, setApiKeyCreatedSecret, setApiKeyLoading, setApiKeyError });
    },
    [apiKeyExpiresAt, apiKeyName, apiKeyScopes, apiKeyUser, readJson],
  );

  const revokeApiKey = useCallback(
    async (key: AdminUserApiKeyRow) => {
      if (!apiKeyUser) return;
      if (!confirm(`Revoke API key "${key.name}"?`)) return;
      await revokeUserApiKey(readJson, apiKeyUser, key, { setApiKeys, setApiKeyCreatedSecret, setApiKeyLoading, setApiKeyError });
    },
    [apiKeyUser, readJson],
  );

  return {
    apiKeyCreatedSecret, apiKeyError, apiKeyExpiresAt, apiKeyLoading, apiKeyName, apiKeyScopes, apiKeys, apiKeyUser,
    closeApiKeyDialog, createApiKey, loadUserApiKeys, revokeApiKey, setApiKeyExpiresAt, setApiKeyName, setApiKeyScopes,
  };
}
