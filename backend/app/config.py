import ipaddress
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import SettingsConfigDict

from .channel_webhook_dev_policy import validate_channel_webhook_dev_setting
from .four_eyes_dev_policy import dev_self_approval_environment_permitted
from .knowledge_snapshot_settings import KnowledgeSnapshotSettings
from .loopback_stub_policy import validate_loopback_allowlist_setting
from .multipart_admission_policy import (
    DEFAULT_MULTIPART_REQUEST_BYTES,
    MultipartAdmissionConfigError,
    validate_multipart_request_bytes,
)
from .rate_limit_settings import RateLimitSettings
from .rate_limit_state_policy import RateLimitRetentionConfigError, validate_max_rate_limit_keys
from .settings_validation_policy import SettingsFieldError, load_validated_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_DATABASE_PROFILES = {"local", "dev", "development", "test", "testing"}
_JWT_SECRET_INSECURE_DEFAULTS = {"change-me-in-production", "change-me-to-a-random-secret-min-32-chars", ""}
_ENCRYPTION_KEY_INSECURE_DEFAULTS = {"change-me-32-chars-long-secret!", "change-me-to-32-char-encryption-key", ""}
_ADMIN_PASSWORD_INSECURE_DEFAULTS = {"admin", "password"}
_ADMIN_EMAIL_INSECURE_DEFAULTS = {"admin@localhost", "", "admin@example.com"}
_FORWARDED_TRUST_DISABLED = "disabled"
_FORWARDED_TRUST_ALLOWLIST = "explicit_allowlist"


def _normalize_runtime_profile(profile: str | None) -> str:
    normalized = str(profile or "").strip().lower().replace("_", "-")
    return normalized or "local"


def _is_sqlite_database_url(url: str) -> bool:
    return str(url or "").startswith(("sqlite+aiosqlite://", "sqlite://"))


def is_production_like_runtime_profile(profile: str | None) -> bool:
    """True for every runtime profile that is not an explicit local/test one."""
    return _normalize_runtime_profile(profile) not in _LOCAL_DATABASE_PROFILES


class TrustedProxyAllowlistError(ValueError):
    """Explicit rejection of a trusted-proxy allowlist.

    Carries a fixed, input-free message so the startup error can be surfaced
    verbatim without echoing the configured value.
    """


_IP_ADDRESS_SPACE_SIZES = {4: 2**32, 6: 2**128}


def _reject_full_address_space_coverage(
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> None:
    """Reject an allowlist whose networks together cover a whole address family.

    A single trust-all entry is caught per entry, but a *composite* set can say
    the same thing without any one entry looking wide: ``0.0.0.0/1`` plus
    ``128.0.0.0/1`` is trust-all for IPv4, and ``::/1`` plus ``8000::/1`` is
    trust-all for IPv6. Collapsing each family answers the question exactly —
    complete coverage always merges into a zero-prefix network, while ordinary
    narrow or merely adjacent CIDRs never do.
    """
    for version, size in _IP_ADDRESS_SPACE_SIZES.items():
        family = [network for network in networks if network.version == version]
        if not family:
            continue
        collapsed = list(ipaddress.collapse_addresses(family))
        if sum(network.num_addresses for network in collapsed) >= size:
            raise TrustedProxyAllowlistError(
                f"trusted_proxy_ips must not cover the entire IPv{version} address space, "
                "not even as a combination of entries; name the reverse proxies as narrowly "
                "as the deployment allows"
            )


def parse_trusted_proxy_ips(raw: str | None) -> list[str]:
    """Normalize a comma-separated trusted-proxy allowlist of IPs or CIDRs.

    Invalid entries raise ``ValueError`` so a typo fails startup instead of
    silently widening or narrowing the proxy trust boundary. Trust-all entries
    (``*``, ``0.0.0.0/0``, ``::/0``) are rejected as well, and so is any set of
    entries that together covers a whole address family: the boundary must name
    the proxies it trusts.

    Keep the list as narrow as the deployment allows: every address it names may
    speak for any client, so a broad network (a whole pod/VPC CIDR) lets any
    workload inside it forge its own client address and scheme.
    """
    values: list[str] = []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in str(raw or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        network = ipaddress.ip_network(candidate, strict=False)
        if int(network.network_address) == 0 and network.prefixlen == 0:
            raise TrustedProxyAllowlistError(
                "trusted_proxy_ips must name individual proxies or proxy networks; "
                "a trust-all entry is not accepted"
            )
        normalized = str(network)
        if normalized not in values:
            values.append(normalized)
            networks.append(network)
    _reject_full_address_space_coverage(networks)
    return values


def forwarded_header_trust_mode(raw: str | None) -> str:
    """Enum-like description of the proxy trust boundary for health reporting."""
    return _FORWARDED_TRUST_ALLOWLIST if parse_trusted_proxy_ips(raw) else _FORWARDED_TRUST_DISABLED


@lru_cache(maxsize=32)
def trusted_proxy_networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parsed trusted-proxy networks for an already validated setting value."""
    return tuple(ipaddress.ip_network(entry) for entry in parse_trusted_proxy_ips(raw))


def _normalize_database_url(url: str) -> str:
    if not isinstance(url, str):
        return url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if not url.startswith(prefix):
            continue
        raw_path = url[len(prefix) :].strip()
        if not raw_path or raw_path == ":memory:":
            return url
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return f"{prefix}{path}"
        return f"{prefix}{(_REPO_ROOT / path).resolve()}"
    return url


def _normalize_filesystem_path(path_value: str) -> str:
    path = Path(str(path_value or "").strip() or "data/artifacts").expanduser()
    if path.is_absolute():
        return str(path.resolve())
    return str((_REPO_ROOT / path).resolve())


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _security_sensitive_default_fields(settings: "Settings") -> list[str]:
    fields: list[str] = []
    if settings.jwt_secret in _JWT_SECRET_INSECURE_DEFAULTS:
        _append_unique(fields, "jwt_secret")
    if settings.encryption_key in _ENCRYPTION_KEY_INSECURE_DEFAULTS:
        _append_unique(fields, "encryption_key")
    # An empty admin_default_password is the secure default: the first-start setup creates the admin
    # (services/auth/first_admin.py). Only a seeded password and its e-mail can be insecure defaults.
    if settings.admin_default_password:
        if settings.admin_default_password in _ADMIN_PASSWORD_INSECURE_DEFAULTS:
            _append_unique(fields, "admin_default_password")
        if settings.admin_email in _ADMIN_EMAIL_INSECURE_DEFAULTS:
            _append_unique(fields, "admin_email")
    if "*" in str(settings.cors_allowed_origins or ""):
        _append_unique(fields, "cors_allowed_origins")
    if settings.auth_cookie_samesite == "none" and not settings.force_secure_auth_cookies:
        _append_unique(fields, "force_secure_auth_cookies")
    if not settings.force_secure_auth_cookies:
        _append_unique(fields, "force_secure_auth_cookies")
    return fields


class Settings(RateLimitSettings, KnowledgeSnapshotSettings):  # see rate_limit_ / knowledge_snapshot_settings.py
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8")

    app_name: str = "Octryx"
    app_version: str = "0.0.1-alpha"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///data/octryx.db"
    # The API's connection pool (server databases only; env DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT). The
    # defaults are SQLAlchemy's; a shared deployment uses 10 + 20 and 10 s (5 + 10 was exhausted by one admin
    # page); the same is recommended for the chart and production.
    db_pool_size: int = Field(default=5, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=400)
    db_pool_timeout: float = Field(default=30.0, gt=0, le=300)
    runtime_profile: str = Field(
        default="local",
        validation_alias=AliasChoices(
            "runtime_profile",
            "OCTRYX_RUNTIME_PROFILE",
            "OCTRYX_ENV",
            "APP_ENV",
        ),
    )
    # Four-eyes development exception: lets one developer approve their
    # own governance request on a machine-local stack. Startup refuses it anywhere
    # production is not positively excluded (see four_eyes_dev_policy).
    four_eyes_dev_self_approval: bool = Field(
        default=False,
        validation_alias=AliasChoices("four_eyes_dev_self_approval", "OCTRYX_FOUR_EYES_DEV_SELF_APPROVAL"),
    )
    # Development-only: accept channel webhooks without their channel's authentication (local
    # stubs). Refused at startup and per request outside DEBUG on a machine-local stack
    # (see channel_webhook_dev_policy). Never set in Helm/EKS.
    channel_webhook_dev_unauthenticated: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "channel_webhook_dev_unauthenticated", "OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED"
        ),
    )
    # Development-only exemption for local loopback stubs (Source Sync and the
    # connector tools alike), gated like the four-eyes exception (see
    # loopback_stub_policy). Never set in Helm/EKS.
    source_sync_allow_loopback_hosts: str = Field(
        default="",
        validation_alias=AliasChoices(
            "source_sync_allow_loopback_hosts", "OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS"
        ),
    )

    # The forward proxy of the uncredentialed web fetches (``services/outbound_egress/public_web.py``).
    # Unset by default: they connect directly and never read HTTP(S)_PROXY from the environment.
    web_fetch_proxy_url: str = Field(
        default="",
        validation_alias=AliasChoices("web_fetch_proxy_url", "OCTRYX_WEB_FETCH_PROXY_URL"),
    )

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    # bcrypt work factor of passwords and stored token/secret hashes (bcrypt's own default, 12). The test suite
    # sets 4 (tests/conftest.py): the hashing stays real bcrypt, only cheaper. Existing hashes keep their own cost.
    auth_bcrypt_rounds: int = Field(
        default=12,
        ge=4,
        le=31,
        validation_alias=AliasChoices("auth_bcrypt_rounds", "OCTRYX_AUTH_BCRYPT_ROUNDS"),
    )

    # Encryption
    encryption_key: str = "change-me-32-chars-long-secret!"

    # Git identity used for platform-authored commits (agent deliveries,
    # repository bootstrap). Override per deployment via env/.env.
    git_commit_user_name: str = Field(
        default="Octryx Bot",
        validation_alias=AliasChoices("git_commit_user_name", "OCTRYX_GIT_USER_NAME"),
    )
    git_commit_user_email: str = Field(
        default="octryx@local",
        validation_alias=AliasChoices("git_commit_user_email", "OCTRYX_GIT_USER_EMAIL"),
    )

    # LLM Providers
    llm_provider: str = ""
    openrouter_api_key: str | None = None
    # The first start's model access for LLM_PROVIDER=anthropic|openai (services/control_plane/env_model_access.py).
    llm_api_key: str | None = None
    llm_endpoint_url: str | None = None
    copilot_token: str | None = None
    copilot_oauth_client_id: str = ""
    aws_region: str = "eu-central-1"
    aws_bedrock_role_arn: str | None = None

    # Knowledge-base embeddings (.env-friendly: consulted when the process
    # environment does not set OCTRYX_KNOWLEDGE_EMBEDDING_PROVIDER/_MODEL)
    knowledge_embedding_provider: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "knowledge_embedding_provider",
            "OCTRYX_KNOWLEDGE_EMBEDDING_PROVIDER",
        ),
    )
    knowledge_embedding_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "knowledge_embedding_model",
            "OCTRYX_KNOWLEDGE_EMBEDDING_MODEL",
        ),
    )
    # Optional cross-encoder reranker for retrieved passages (explicit opt-in;
    # e.g. "BAAI/bge-reranker-base"). None/off disables reranking.
    knowledge_reranker_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "knowledge_reranker_model",
            "OCTRYX_KNOWLEDGE_RERANKER_MODEL",
        ),
    )

    # Opt-in Instance default Workspace data classification ("public", "internal", ...), written once
    # when Knowledge is enabled for a Workspace without one, so the data-policy gate can admit its
    # remote Knowledge models (reranker). Empty: Workspaces stay unclassified until an admin sets it.
    knowledge_default_data_classification: str = Field(
        default="",
        validation_alias=AliasChoices(
            "knowledge_default_data_classification",
            "OCTRYX_KNOWLEDGE_DEFAULT_DATA_CLASSIFICATION",
        ),
    )

    # Exact origin (scheme://host[:port]) serving the static Agent Designer artifact
    #Unset means the admin Designer tab reports needs_configuration.
    agent_designer_origin: str | None = Field(
        default=None,
        validation_alias=AliasChoices("agent_designer_origin", "OCTRYX_AGENT_DESIGNER_ORIGIN"),
    )

    # Turn runtime behind the execution gate. Every value runs the native
    # standard loop; a value other than "native" is logged as a warning
    # (app/agent/harness/activation.py records why).
    harness_runtime: str = Field(
        default="native",
        validation_alias=AliasChoices("harness_runtime", "OCTRYX_HARNESS_RUNTIME"),
    )

    # Exact public origin (scheme://host[:port]) of the platform UI. Session-episode citations
    # link to the session under it; unset means episode writes report needs_configuration.
    platform_public_origin: str | None = Field(
        default=None,
        validation_alias=AliasChoices("platform_public_origin", "OCTRYX_PUBLIC_ORIGIN"),
    )

    # Octryx Mobile push: the platform's VAPID key (P-256, base64url raw or PEM; from the deployment's
    # secret store) and the contact it names to push services. Unset: no push.
    mobile_vapid_private_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mobile_vapid_private_key", "MOBILE_VAPID_PRIVATE_KEY"),
    )
    mobile_vapid_subject: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mobile_vapid_subject", "MOBILE_VAPID_SUBJECT"),
    )

    # HMAC key for entity-graph federation packages (hub-and-spoke). Empty
    # means federation endpoints refuse with needs_configuration — never a
    # default key.
    knowledge_federation_signing_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "knowledge_federation_signing_key",
            "OCTRYX_KNOWLEDGE_FEDERATION_SIGNING_KEY",
        ),
    )

    # Native pgvector column dimension; consumed (via the environment) by the
    # pgvector migrations when provisioning a fresh PostgreSQL database.
    knowledge_embedding_dimension: int = Field(
        default=1024,
        validation_alias=AliasChoices(
            "knowledge_embedding_dimension",
            "OCTRYX_KNOWLEDGE_EMBEDDING_DIMENSION",
        ),
    )

    # Telegram
    telegram_bot_token: str | None = None

    # Observability: a Prometheus scraper presents this as a bearer token on /metrics (unset: login only).
    metrics_scrape_token: str | None = None
    # A pending approval nobody decided within this many hours expires (audited); 0 never expires.
    approval_pending_ttl_hours: int = 72

    # Bootstrap
    # Unattended installs only; empty means the first-start setup creates the admin (services/auth/first_admin.py).
    admin_default_password: str = ""
    admin_email: str = "admin@localhost"
    seed_demo_project: bool = False

    # Platform feature switches: server config/env only, never settable from the UI.
    # Branding (custom app name/logo) is off until it is released (BRANDING_ENABLED).
    branding_enabled: bool = False
    # "Proposed checks" (From Correction to Check) against fixtures until the signature store and the proposal
    # service exist. None: on in a local runtime profile only, never on a production-like one.
    check_proposals_stub: bool | None = None

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_allowed_origins: str = (
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173"
    )
    redis_url: str | None = None
    artifact_store_backend: str = "filesystem"
    artifact_store_dir: str = "data/artifacts"
    artifact_store_bucket: str | None = None
    artifact_store_prefix: str = ""
    artifact_store_s3_region: str | None = None
    artifact_store_s3_endpoint_url: str | None = None
    auth_cookie_samesite: str = "lax"
    force_secure_auth_cookies: bool = False
    # Reverse proxies whose forwarded request metadata may be trusted, as a
    # comma-separated list of IPs or CIDRs. Empty means deny-by-default: no
    # forwarded header is read. Set this for ingress/reverse-proxy deployments.
    trusted_proxy_ips: str = Field(
        default="",
        validation_alias=AliasChoices("trusted_proxy_ips", "OCTRYX_TRUSTED_PROXY_IPS"),
    )
    # Hard ceiling on raw multipart request bytes, enforced before any form
    # parsing. The default is derived from the largest payload a current upload
    # route accepts, so the boundary cannot refuse an upload the product accepts;
    # lower it to the largest upload a deployment actually needs. Invalid or
    # effectively unbounded values fail startup — see multipart_admission_policy.
    max_multipart_request_bytes: int = Field(
        default=DEFAULT_MULTIPART_REQUEST_BYTES,
        validation_alias=AliasChoices(
            "max_multipart_request_bytes",
            "OCTRYX_MAX_MULTIPART_REQUEST_BYTES",
        ),
    )

    # Agent
    agent_max_tool_calls_per_session: int = 50
    agent_default_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    engineering_knowledge_repo_search_roots: str = ""
    # The code graph's repository mirrors: a shallow clone per Workspace repository under
    # this folder (an external disk on the Mac); empty: the platform keeps no mirror.
    code_mirror_root: str = Field(default="", validation_alias=AliasChoices("OCTRYX_CODE_MIRROR_ROOT",
                                                                            "CODE_MIRROR_ROOT"))

    @model_validator(mode="after")
    def normalize_paths(self):
        self.database_url = _normalize_database_url(self.database_url)
        self.artifact_store_dir = _normalize_filesystem_path(self.artifact_store_dir)
        self.runtime_profile = _normalize_runtime_profile(self.runtime_profile)
        return self

    @model_validator(mode="after")
    def validate_database_profile(self):
        if _is_sqlite_database_url(self.database_url) and is_production_like_runtime_profile(self.runtime_profile):
            # The profile name is an input value like any other: the fields
            # are named, the configured values are not.
            raise SettingsFieldError(
                "sqlite_database_url_in_production_like_profile",
                "SQLite database_url is local/test only. Use PostgreSQL for a production-like runtime_profile.",
                ("database_url", "runtime_profile"),
            )
        return self

    @model_validator(mode="after")
    def validate_multipart_admission_ceiling(self):
        """Fail closed on an invalid or effectively unbounded ingress ceiling.

        Deliberately has no debug/local escape hatch: an admission ceiling nobody
        chose is a resource-exhaustion boundary nobody chose, in every profile.
        """
        try:
            self.max_multipart_request_bytes = validate_multipart_request_bytes(self.max_multipart_request_bytes)
        except MultipartAdmissionConfigError as exc:
            # Message is a fixed policy statement and never echoes the value.
            raise SettingsFieldError(
                "invalid_multipart_request_ceiling", str(exc), ("max_multipart_request_bytes",)
            ) from exc
        return self

    @model_validator(mode="after")
    def validate_rate_limit_key_bound(self):
        """Fail closed on a rate-limit key bound that would not bound anything.

        Like the multipart ceiling, this has no local/debug escape hatch: limiter
        state nobody bounded is a memory-growth surface in every profile, and the
        bound becomes load-bearing the moment TRUSTED_PROXY_IPS is configured.
        """
        try:
            self.max_rate_limit_keys = validate_max_rate_limit_keys(self.max_rate_limit_keys)
        except RateLimitRetentionConfigError as exc:
            # Message is a fixed policy statement and never echoes the value.
            raise SettingsFieldError(
                "invalid_rate_limit_key_bound", str(exc), ("max_rate_limit_keys",)
            ) from exc
        return self

    @model_validator(mode="after")
    def validate_security_sensitive_defaults(self):
        self.auth_cookie_samesite = str(self.auth_cookie_samesite or "lax").strip().lower()
        if self.auth_cookie_samesite not in {"lax", "strict", "none"}:
            raise SettingsFieldError(
                "unsupported_auth_cookie_samesite",
                "auth_cookie_samesite must be one of: lax, strict, none",
                ("auth_cookie_samesite",),
            )

        try:
            self.trusted_proxy_ips = ",".join(parse_trusted_proxy_ips(self.trusted_proxy_ips))
        except TrustedProxyAllowlistError as exc:
            # Message is a fixed policy statement, safe to surface verbatim.
            raise SettingsFieldError(
                "trusted_proxy_allowlist_too_broad", str(exc), ("trusted_proxy_ips",)
            ) from exc
        except ValueError:
            # ``from None``: ipaddress quotes the rejected entry in its own message,
            # so that exception must not stay reachable as this one's cause.
            raise SettingsFieldError(
                "malformed_trusted_proxy_allowlist",
                "trusted_proxy_ips must be a comma-separated list of IP addresses or CIDR networks",
                ("trusted_proxy_ips",),
            ) from None

        production_like_profile = is_production_like_runtime_profile(self.runtime_profile)
        if self.debug and not production_like_profile:
            return self

        insecure_fields = _security_sensitive_default_fields(self)
        if insecure_fields:
            raise SettingsFieldError(
                "insecure_default_configuration",
                "Insecure default configuration. Set secure values via environment or .env "
                "before starting the app.",
                insecure_fields,
            )
        return self

    @model_validator(mode="after")
    def validate_four_eyes_dev_exception(self):
        """Fail closed: the self-approval exception never starts outside development."""
        if self.four_eyes_dev_self_approval and not dev_self_approval_environment_permitted(
            self.runtime_profile, self.cors_allowed_origins
        ):
            raise SettingsFieldError(
                "four_eyes_dev_exception_outside_development",
                "The four-eyes self-approval exception is development-only. Unset it, or run a "
                "non-production runtime_profile whose cors_allowed_origins are all loopback.",
                ("four_eyes_dev_self_approval", "runtime_profile", "cors_allowed_origins"),
            )
        return self

    @model_validator(mode="after")
    def validate_channel_webhook_dev_exception(self):
        validate_channel_webhook_dev_setting(
            self.channel_webhook_dev_unauthenticated, self.debug, self.runtime_profile, self.cors_allowed_origins
        )
        return self

    @model_validator(mode="after")
    def validate_loopback_stub_exemption(self):
        """Fail closed: the loopback stub exemption never starts outside development."""
        validate_loopback_allowlist_setting(
            self.source_sync_allow_loopback_hosts, self.runtime_profile, self.cors_allowed_origins
        )
        return self

    def security_defaults_report(self) -> dict[str, object]:
        production_like_profile = is_production_like_runtime_profile(self.runtime_profile)
        local_only_fields = _security_sensitive_default_fields(self)
        local_only_defaults_allowed = bool(self.debug and not production_like_profile)
        if not local_only_fields:
            status = "secure"
        elif local_only_defaults_allowed:
            status = "local_only_defaults"
        else:
            status = "blocked_by_startup_validation"
        return {
            "status": status,
            "runtime_profile": self.runtime_profile,
            "production_like": production_like_profile,
            "debug": bool(self.debug),
            "local_only_defaults_allowed": local_only_defaults_allowed,
            "local_only_default_fields": local_only_fields,
            # Auth-cookie policy inputs (booleans only, never values): they make a
            # local-debug runtime visibly non-production on the health endpoint.
            "force_secure_auth_cookies": bool(self.force_secure_auth_cookies),
            "trusted_proxy_ips_configured": bool(parse_trusted_proxy_ips(self.trusted_proxy_ips)),
            # Forwarded headers are only read for peers in the allowlist,
            # so an ingress deployment can verify the boundary from /api/v1/health.
            "forwarded_header_trust": forwarded_header_trust_mode(self.trusted_proxy_ips),
        }


@lru_cache
def get_settings() -> Settings:
    """The one settings entrypoint for every startup path.

    Construction goes through ``load_validated_settings`` so an invalid
    configuration fails closed with an input-free ``SettingsValidationError``
    instead of Pydantic's rendering of the settings payload.
    """
    return load_validated_settings(Settings)


def git_commit_identity() -> tuple[tuple[str, str], tuple[str, str]]:
    """Git config pairs for platform-authored commits."""
    resolved = get_settings()
    return (
        ("user.name", resolved.git_commit_user_name),
        ("user.email", resolved.git_commit_user_email),
    )
