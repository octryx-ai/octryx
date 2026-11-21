# Local LiteLLM data-plane qualification fixture

A deterministic, LiteLLM-compatible HTTPS endpoint on loopback, plus a real
`CONNECT` proxy, used to qualify the governed `litellm_gateway` adapter
(`backend/app/services/model_gateway/litellm/`) before the driver may be enabled in
a shared environment.

This is a **contract fixture**, not a LiteLLM deployment. It speaks the surface the
adapter pins — `GET /v1/models` with `model_info.supports_*`, `POST
/v1/chat/completions` with `usage` and an optional `usage.cost` / `response_cost` —
so the product's admission, capability, usage, cost and failure contracts are
exercised over a real socket. It proves nothing about the cluster's LiteLLM
version, virtual-key scope, content-logging configuration, model groups or cost
shape; that remains an external gate, and the written report says so.

## Run

```bash
deployment/local/litellm-gateway/fixture.sh
# from a worktree without backend/.venv:
OCTRYX_PYTHON=/path/to/octryx/backend/.venv/bin/python deployment/local/litellm-gateway/fixture.sh
```

The script scopes `DEBUG=true` to the fixture subprocess so the repository's
documented local-only bootstrap defaults can initialize; it does not export that
profile to a service, shared environment, or deployment.

Exit code `0` means every required check passed. Exit code `1` means a check
failed, a required check was missing, or the run tried to present itself as live
evidence.

The product evidence writer stores the local fixture report under the git-ignored
evidence directory and refuses any other path.

## What the run proves

| Step | Claim |
|---|---|
| 1 | Each admitted alias reports integral prompt/completion usage, settles its declared cost contract (`gateway_reported` strictly positive, `governed_free` zero, `catalog_pricing` positive), names the governed model group, and has its declared capabilities backed by `model_info.supports_*`. |
| 1 | Hostile ambient `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY` are exported for the whole run, pointing at a closed loopback port, and every call still succeeds — so a client that honoured one would have reached no gateway at all. |
| 1 | The virtual key reaches the gateway (the fixture matched the bearer on every request) and appears in no evidence, log line or error. |
| 2 | A substituted model group, absent usage, a zero `gateway_reported` cost, a positive `governed_free` cost, a `catalog_pricing` result that prices to zero, and an unproven capability request are each refused with their expected state and a fixed message. |
| 3 | The configured private CA bundle *is* the trust store: the same endpoint and certificate are refused as `gateway_unreachable` when only a foreign CA is configured, with no OpenSSL text in the error. |
| 3 | The ambient CA variables (`SSL_CERT_FILE`/`SSL_CERT_DIR`/`REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE`) are ignored, proven *discriminatingly*: for this step they point at the **genuine** CA while the product is configured with only the **foreign** one, so honouring any of them would turn that refusal into a success. The built trust store is then read back and must hold exactly the configured anchor. |
| 4 | A governed proxy really carries the call: the `CONNECT` tunnel to the gateway is observed at the proxy, and the direct run never touches it. |
| 5 | The report is closed and secret-free, carries the least-privilege network path, and records `evidence_origin=local_contract_fixture` with `live_evidence_state=pending_external_gate` plus the `live_evidence_blocking_reason` that held the gate open, so a local run can never close the activation gate. |

## Negative controls

These controls verify that the harness distinguishes the configured endpoint and CA
from ambient settings: each one, applied, must change the result as shown.

| Control | Observed |
|---|---|
| `trust_env=True` in the adapter's transport policy | Run fails (exit `1`): the sinkhole proxy variables take effect. |
| `load_default_certs()` added to the trust store builder, i.e. the client honours `SSL_CERT_FILE`/`SSL_CERT_DIR` | Run fails: `private_ca_trust_enforced` and `ambient_ca_environment_ignored` both fail. |
| The same control, but with the ambient CA variables pointed at the *foreign* bundle | Run **passes**, because the configured private CA already trusts the server, so an extra ambient anchor changes no result. That is why step 3 points them at the genuine CA. |

## Files

| File | Responsibility |
|---|---|
| `fixture.sh` | Generates throwaway TLS material and a throwaway virtual key outside the repository, runs the smoke, cleans up. |
| `fixture_contract.py` | The pinned contract: alias catalog, catalog payload, per-scenario response, provider `config_json`. |
| `tls_material.py` | Test-only CA, `127.0.0.1` server certificate, and an unrelated foreign CA (its own subject, so a check can assert *which* anchors a trust store holds) for the trust-store check. |
| `gateway_fixture.py` | The TLS HTTP server. Records method, path and whether the bearer matched — never the header value or a body. |
| `forward_proxy.py` | Minimal `CONNECT` proxy. Records tunnel targets, forwards the TLS payload without inspecting it. |
| `qualification_smoke.py` | Drives the product client and qualification service, then writes the report through the product evidence writer. |

## Boundaries

- No `.env` file and no application settings are loaded; no database is touched.
- No credential, TLS private key, request body, response body, authorization header
  or server error text is printed.
- The generated key material is test-only, lives outside the repository, and is
  deleted when the run ends. It must never be committed or reused.
- Required before shared-environment activation: the same qualification against the
  cluster gateway, with `evidence_origin=external_live_gateway` and a
  `content_logging.verified_against=live_gateway_configuration` posture. Only then
  does `gate_satisfied` become true.
- Those two are declarations, so they are not sufficient on their own: the run must
  also have used a **non-loopback endpoint over TLS**, which is a validated fact
  about the configuration rather than a caller argument. That is why this fixture —
  which answers on `127.0.0.1` — cannot close the gate even if both declarations are
  flipped, and why the report names the condition that blocked it.
- What that gate is *not*: cryptographic proof. A non-loopback TLS endpoint whose
  name is on the host allowlist is evidence that the run left this machine, not
  attestation that the peer was the governed cluster gateway. Closing the gate is
  therefore a **coordinator review** of the produced report against the environment
  the coordinator knows — endpoint, CA chain, virtual-key scope, model groups,
  content-logging configuration — not an automated verdict the backend can reach
  on its own.
