"""Text-to-Speech provider system with fallback chain."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select

from app.services.error_facts import error_text

from ...time_utils import utc_now

logger = logging.getLogger(__name__)


class TTSProvider(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, text: str, voice: str, speed: float) -> bytes: ...


class OpenAITTSProvider(TTSProvider):
    name = "openai"

    VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    DEFAULT_VOICE = "alloy"

    def __init__(self, api_key: str, base_url: str | None = None, model: str = "tts-1"):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com"
        self._model = model

    async def synthesize(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
        if voice not in self.VOICES:
            voice = self.DEFAULT_VOICE
        speed = max(0.25, min(4.0, speed))
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "input": text,
                    "voice": voice,
                    "speed": speed,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
            return response.content


class ElevenLabsTTSProvider(TTSProvider):
    name = "elevenlabs"

    DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

    def __init__(self, api_key: str, base_url: str | None = None, model: str = "eleven_monolingual_v1"):
        self._api_key = api_key
        self._base_url = base_url or "https://api.elevenlabs.io"
        self._model = model

    async def synthesize(self, text: str, voice: str = DEFAULT_VOICE_ID, speed: float = 1.0) -> bytes:
        voice_id = voice if voice else self.DEFAULT_VOICE_ID
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self._model,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "speed": speed,
                    },
                },
            )
            response.raise_for_status()
            return response.content


class AwsPollyTTSProvider(TTSProvider):
    name = "aws_polly"

    DEFAULT_VOICE = "Matthew"
    VOICES = [
        "Matthew",
        "Joanna",
        "Ivy",
        "Kendra",
        "Kimberly",
        "Salli",
        "Joey",
        "Justin",
        "Kevin",
        "Ruth",
        "Stephen",
        "Geraint",
        "Nicole",
        "Olivia",
        "Amy",
        "Emma",
        "Brian",
        "Aria",
        "Ayanda",
        "Arlo",
        "Hiujin",
        "Ida",
        "Arthur",
        "Bianca",
        "Carmen",
        "Dora",
        "Elin",
    ]

    def __init__(self, aws_access_key_id: str, aws_secret_access_key: str, region: str = "us-east-1"):
        self._access_key = aws_access_key_id
        self._secret_key = aws_secret_access_key
        self._region = region

    async def synthesize(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
        import boto3

        speed_percent = int(speed * 100)
        client = boto3.client(
            "polly",
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        )
        response = client.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            VoiceId=voice,
            Engine="neural",
            Speed=f"{speed_percent}%",
        )
        return response["AudioStream"].read()


_BROWSER_PROVIDER_ID = "browser"
_SYNTHESIS = "tts.synthesis"
_PROVIDER_STATUS = "tts.provider_status"


async def _tts_key(db, field_name: str, purpose: str) -> str | None:
    from ..secret import get_secret_value

    return await get_secret_value(db, tool_name="tts", field_name=field_name, purpose=purpose)


@dataclass(frozen=True)
class TTSProviderAttempt:
    provider: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TTSProviderResolution:
    provider: TTSProvider | None
    selected_provider: str | None
    fallback_allowed: bool
    fallback_used: bool = False
    attempts: list[TTSProviderAttempt] = field(default_factory=list)

    def to_audit_dict(self) -> dict:
        return {
            "selected_provider": self.selected_provider,
            "fallback_allowed": self.fallback_allowed,
            "fallback_used": self.fallback_used,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass
class TTSProviderConfig:
    provider: str
    enabled: bool = True
    priority: int = 0
    config: dict = field(default_factory=dict)


@dataclass
class TTSConfig:
    enabled: bool = False
    default_voice: str = "alloy"
    default_speed: float = 1.0
    allow_provider_fallback: bool = True
    providers: list[TTSProviderConfig] = field(default_factory=list)


def normalize_tts_config(config: TTSConfig) -> TTSConfig:
    """Preserve installed providers while enforcing policy-compatible activation."""
    enabled_seen = False
    normalized_providers: list[TTSProviderConfig] = []
    for provider in sorted(config.providers, key=lambda item: item.priority):
        provider_id = str(provider.provider or "").strip()
        if not provider_id:
            continue
        is_enabled = bool(provider.enabled)
        if is_enabled and enabled_seen and not config.allow_provider_fallback:
            is_enabled = False
        if is_enabled:
            enabled_seen = True
        normalized_providers.append(
            TTSProviderConfig(
                provider=provider_id,
                enabled=is_enabled,
                priority=provider.priority,
                config=dict(provider.config or {}),
            )
        )
    config.providers = normalized_providers
    if config.enabled and not enabled_seen:
        config.enabled = False
    return config


async def load_tts_config(db, project_id: str | None = None) -> TTSConfig:
    """Load TTS configuration from database."""
    import json

    from ...models import Project
    from ..secret import get_secret_value

    stored = await get_secret_value(db, tool_name="tts_config", field_name="config", project_id=None,
                                    purpose="tts.settings")
    config_data: dict = {}
    if stored:
        try:
            config_data = json.loads(stored)
        except ValueError:
            pass

    # Project-scoped override: merge project.config.tts on top of global
    if project_id:
        proj_result = await db.execute(select(Project).where(Project.id == project_id))
        project = proj_result.scalar_one_or_none()
        if project and project.config and isinstance(project.config, dict):
            proj_tts = project.config.get("tts")
            if isinstance(proj_tts, dict):
                # Merge: project settings win over global defaults
                config_data = {
                    **config_data,
                    "enabled": proj_tts.get("enabled", config_data.get("enabled", False)),
                "default_voice": proj_tts.get("default_voice", config_data.get("default_voice", "alloy")),
                "default_speed": proj_tts.get("default_speed", config_data.get("default_speed", 1.0)),
                "allow_provider_fallback": proj_tts.get(
                    "allow_provider_fallback",
                    config_data.get("allow_provider_fallback", True),
                ),
            }

    providers = []
    for p in config_data.get("providers", []):
        providers.append(
            TTSProviderConfig(
                provider=p.get("provider", ""),
                enabled=p.get("enabled", True),
                priority=p.get("priority", 0),
                config=p.get("config", {}),
            )
        )

    return normalize_tts_config(
        TTSConfig(
            enabled=config_data.get("enabled", False),
            default_voice=config_data.get("default_voice", "alloy"),
            default_speed=config_data.get("default_speed", 1.0),
            allow_provider_fallback=config_data.get("allow_provider_fallback", True),
            providers=providers,
        )
    )


async def save_tts_config(db, config: TTSConfig) -> None:
    """Save TTS configuration to database."""
    import json

    from ...models import StoredSecret
    from ..secret import encrypt_secret, get_secret_entry

    config = normalize_tts_config(config)
    config_data = {
        "enabled": config.enabled,
        "default_voice": config.default_voice,
        "default_speed": config.default_speed,
        "allow_provider_fallback": config.allow_provider_fallback,
        "providers": [
            {
                "provider": p.provider,
                "enabled": p.enabled,
                "priority": p.priority,
                "config": p.config,
            }
            for p in config.providers
        ],
    }

    encrypted = encrypt_secret(json.dumps(config_data))

    existing = await get_secret_entry(db, tool_name="tts_config", field_name="config", project_id=None)
    if existing:
        existing.encrypted_value = encrypted
        existing.last_rotated_at = utc_now()
    else:
        secret = StoredSecret(
            name="tts_config_config",
            secret_type="tts_config",
            tool_name="tts_config",
            field_name="config",
            project_id=None,
            encrypted_value=encrypted,
            last_rotated_at=utc_now(),
        )
        db.add(secret)

    await db.commit()


async def _build_tts_provider(db, provider: TTSProviderConfig) -> tuple[TTSProvider | None, str | None]:
    if provider.provider == _BROWSER_PROVIDER_ID:
        return None, "client_side_only"

    if provider.provider == "openai":
        api_key = await _tts_key(db, "openai_api_key", _SYNTHESIS)
        if not api_key:
            return None, "missing_credentials"
        return (
            OpenAITTSProvider(
                api_key,
                base_url=provider.config.get("base_url"),
                model=provider.config.get("model", "tts-1"),
            ),
            None,
        )

    if provider.provider == "elevenlabs":
        api_key = await _tts_key(db, "elevenlabs_api_key", _SYNTHESIS)
        if not api_key:
            return None, "missing_credentials"
        return (
            ElevenLabsTTSProvider(
                api_key,
                base_url=provider.config.get("base_url"),
                model=provider.config.get("model", "eleven_monolingual_v1"),
            ),
            None,
        )

    if provider.provider == "aws_polly":
        access_key = await _tts_key(db, "aws_access_key_id", _SYNTHESIS)
        secret_key = await _tts_key(db, "aws_secret_access_key", _SYNTHESIS)
        if not access_key or not secret_key:
            return None, "missing_credentials"
        return (
            AwsPollyTTSProvider(
                access_key,
                secret_key,
                region=provider.config.get("region", "us-east-1"),
            ),
            None,
        )

    return None, "unknown_provider"


async def resolve_tts_provider(
    db,
    provider_name: str | None = None,
    project_id: str | None = None,
) -> TTSProviderResolution:
    """Resolve a TTS provider and return policy/audit details for the decision."""
    config = await load_tts_config(db, project_id=project_id)
    attempts: list[TTSProviderAttempt] = []
    fallback_allowed = bool(config.allow_provider_fallback and provider_name is None)

    if not config.enabled and not provider_name:
        logger.debug("TTS: disabled")
        attempts.append(TTSProviderAttempt("tts_config", "skipped", "tts_disabled"))
        return TTSProviderResolution(None, None, fallback_allowed, attempts=attempts)

    if provider_name:
        providers_to_try = [p for p in config.providers if p.provider == provider_name and p.enabled]
        if not providers_to_try:
            attempts.append(TTSProviderAttempt(provider_name, "failed", "requested_provider_not_enabled"))
    else:
        providers_to_try = sorted([p for p in config.providers if p.enabled], key=lambda x: x.priority)
        if not providers_to_try:
            attempts.append(TTSProviderAttempt("tts_config", "failed", "no_enabled_provider"))

    for provider_config in providers_to_try:
        try:
            provider, unavailable_reason = await _build_tts_provider(db, provider_config)
        except Exception as exc:
            reason = f"provider_initialization_failed:{type(exc).__name__}"
            attempts.append(TTSProviderAttempt(provider_config.provider, "failed", reason))
            logger.warning(
                "TTS provider %s failed: %s",
                provider_config.provider,
                error_text("tts_provider_failed", exc),
            )
            if not fallback_allowed:
                attempts.append(TTSProviderAttempt(provider_config.provider, "blocked", "fallback_disabled"))
                return TTSProviderResolution(None, None, fallback_allowed, attempts=attempts)
            continue

        if provider is not None:
            logger.debug("TTS: using %s provider", provider_config.provider)
            attempts.append(TTSProviderAttempt(provider_config.provider, "selected", "provider_available"))
            fallback_used = any(attempt.status == "failed" for attempt in attempts[:-1])
            return TTSProviderResolution(
                provider,
                provider_config.provider,
                fallback_allowed,
                fallback_used=fallback_used,
                attempts=attempts,
            )

        attempts.append(TTSProviderAttempt(provider_config.provider, "failed", unavailable_reason or "unavailable"))
        if not fallback_allowed:
            attempts.append(TTSProviderAttempt(provider_config.provider, "blocked", "fallback_disabled"))
            return TTSProviderResolution(None, None, fallback_allowed, attempts=attempts)

    logger.debug("TTS: no available provider")
    return TTSProviderResolution(None, None, fallback_allowed, attempts=attempts)


async def get_tts_provider(db, provider_name: str | None = None, project_id: str | None = None) -> TTSProvider | None:
    """Get a specific TTS provider or the first available one."""
    return (await resolve_tts_provider(db, provider_name, project_id=project_id)).provider


async def list_tts_providers(db) -> list[dict]:
    """List available TTS providers with their status."""
    config = await load_tts_config(db)
    providers = []

    openai_key = await _tts_key(db, "openai_api_key", _PROVIDER_STATUS)
    elevenlabs_key = await _tts_key(db, "elevenlabs_api_key", _PROVIDER_STATUS)
    aws_key = await _tts_key(db, "aws_access_key_id", _PROVIDER_STATUS)
    aws_secret = await _tts_key(db, "aws_secret_access_key", _PROVIDER_STATUS)

    all_providers = {
        "openai": {"id": "openai", "name": "OpenAI", "voices": OpenAITTSProvider.VOICES, "has_key": bool(openai_key)},
        "elevenlabs": {"id": "elevenlabs", "name": "ElevenLabs", "voices": [], "has_key": bool(elevenlabs_key)},
        "aws_polly": {
            "id": "aws_polly",
            "name": "AWS Polly",
            "voices": AwsPollyTTSProvider.VOICES,
            "has_key": bool(aws_key and aws_secret),
        },
        _BROWSER_PROVIDER_ID: {
            "id": _BROWSER_PROVIDER_ID,
            "name": "Browser",
            "voices": [],
            "has_key": True,
            "key_required": False,
        },
    }

    configured = {p.provider: p for p in config.providers}

    for provider_id, configured_provider in configured.items():
        provider = dict(all_providers.get(provider_id) or {"id": provider_id, "name": provider_id, "voices": []})
        provider.setdefault("has_key", bool(provider_id == _BROWSER_PROVIDER_ID))
        provider.setdefault("key_required", provider_id != _BROWSER_PROVIDER_ID)
        provider["enabled"] = configured_provider.enabled
        provider["priority"] = configured_provider.priority
        provider["installed"] = True
        providers.append(provider)

    return sorted(providers, key=lambda x: x["priority"])


async def is_tts_provider_available(db, provider: TTSProviderConfig) -> bool:
    """Return whether an installed provider can be activated."""
    if provider.provider == _BROWSER_PROVIDER_ID:
        return True
    if provider.provider == "openai":
        return bool(await _tts_key(db, "openai_api_key", _PROVIDER_STATUS))
    if provider.provider == "elevenlabs":
        return bool(await _tts_key(db, "elevenlabs_api_key", _PROVIDER_STATUS))
    if provider.provider == "aws_polly":
        access_key = await _tts_key(db, "aws_access_key_id", _PROVIDER_STATUS)
        secret_key = await _tts_key(db, "aws_secret_access_key", _PROVIDER_STATUS)
        return bool(access_key and secret_key)
    return False


async def has_active_tts_provider(db, config: TTSConfig | None = None, project_id: str | None = None) -> bool:
    config = config or await load_tts_config(db, project_id=project_id)
    config = normalize_tts_config(config)
    for provider in config.providers:
        if provider.enabled and await is_tts_provider_available(db, provider):
            return True
    return False


def serialize_tts_overview(config: TTSConfig, resolution: TTSProviderResolution, *, effective_enabled: bool) -> dict:
    """Shared response body for the TTS config/providers overview."""
    return {
        "enabled": effective_enabled,
        "default_voice": config.default_voice,
        "default_speed": config.default_speed,
        "allow_provider_fallback": config.allow_provider_fallback,
        "fallback_allowed": resolution.fallback_allowed,
        "fallback_used": resolution.fallback_used,
        "resolution": resolution.to_audit_dict(),
    }


def serialize_tts_provider_rows(config: TTSConfig) -> list[dict]:
    """Serialize saved provider rows in priority order for API responses."""
    return [
        {"provider": p.provider, "enabled": p.enabled, "priority": p.priority, "config": p.config}
        for p in config.providers
    ]


async def upsert_tts_provider(
    db,
    *,
    provider: str,
    enabled: bool,
    priority: int,
    config: dict,
) -> TTSConfig:
    """Add or replace a provider, enforcing single-active activation."""
    tts_config = await load_tts_config(db)
    requested_provider = TTSProviderConfig(
        provider=provider,
        enabled=enabled,
        priority=priority,
        config=config,
    )
    if requested_provider.enabled and not await is_tts_provider_available(db, requested_provider):
        raise ValueError("Provider cannot be activated until its credentials are configured.")
    if requested_provider.enabled:
        for existing_provider in tts_config.providers:
            existing_provider.enabled = False
    existing = [i for i, p in enumerate(tts_config.providers) if p.provider == provider]
    if existing:
        tts_config.providers[existing[0]] = requested_provider
    else:
        tts_config.providers.append(requested_provider)
    normalize_tts_config(tts_config)
    tts_config.enabled = any(p.enabled for p in tts_config.providers)
    await save_tts_config(db, tts_config)
    return tts_config


async def remove_tts_provider(db, *, provider_id: str) -> TTSConfig:
    """Remove a provider by id and recompute the enabled flag."""
    config = await load_tts_config(db)
    config.providers = [p for p in config.providers if p.provider != provider_id]
    config.enabled = any(p.enabled for p in config.providers)
    await save_tts_config(db, config)
    return config


async def move_tts_provider(db, *, provider_id: str, direction: str) -> TTSConfig:
    """Swap a provider's priority with its neighbour in the given direction."""
    config = await load_tts_config(db)
    sorted_providers = sorted(config.providers, key=lambda p: p.priority)
    idx = next((i for i, p in enumerate(sorted_providers) if p.provider == provider_id), -1)
    if idx == -1:
        raise KeyError(provider_id)

    new_idx = idx - 1 if direction == "up" else idx + 1
    if new_idx < 0 or new_idx >= len(sorted_providers):
        return config

    provider = sorted_providers[idx]
    other = sorted_providers[new_idx]
    provider.priority, other.priority = other.priority, provider.priority
    await save_tts_config(db, config)
    return config
