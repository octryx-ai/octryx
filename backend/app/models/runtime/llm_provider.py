import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(100), nullable=False)  # openrouter, bedrock, copilot
    provider_family = Column(String(100), nullable=True)
    driver = Column(String(100), nullable=True)
    runtime_kind = Column(String(40), nullable=True)
    display_name = Column(String(200))
    profile_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    endpoint_url = Column(String(1000), nullable=True)
    binary_path = Column(String(1000), nullable=True)
    # Provider credentials live in stored_secrets and are
    # referenced via api_key_secret_ref (see services.control_plane.provider_auth).
    api_key_secret_ref = Column(String(36), nullable=True)
    auth_mode = Column(String(40), nullable=True, default="api_key")
    # OAuth configuration + runtime state live in the provider_oauth_config
    # table (relationship ``oauth_config`` below).
    config_json = Column(JSON, nullable=True)
    capabilities_json = Column(JSON, nullable=True)
    aws_region = Column(String(50), nullable=True)
    aws_role_arn = Column(String(500), nullable=True)
    default_model_id = Column(String(200), nullable=True)
    bootstrap_role = Column(String(40), nullable=True)
    health_status = Column(String(40), nullable=True)
    last_health_check_at = Column(DateTime, nullable=True)
    last_health_error = Column(Text, nullable=True)
    is_global = Column(Boolean, default=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    models = relationship("LLMModel", back_populates="provider")
    oauth_config = relationship(
        "ProviderOAuthConfig",
        back_populates="provider",
        uselist=False,
        cascade="all, delete-orphan",
    )


class LLMModel(Base):
    __tablename__ = "llm_models"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_id = Column(String(36), ForeignKey("llm_providers.id"), nullable=False)
    model_id = Column(String(200), nullable=False)
    display_name = Column(String(200))
    supports_tools = Column(Boolean, default=False)
    supports_vision = Column(Boolean, default=False)
    supports_streaming = Column(Boolean, default=True)
    context_length = Column(Integer)
    planner_context_budget = Column(Integer, nullable=True)
    pricing_input = Column(Float, nullable=True)
    pricing_output = Column(Float, nullable=True)
    # Optional prompt-cache rates (USD per million tokens), written by a governed
    # ``catalog_pricing`` sync or, while no cost source owns the price, by an admin
    # (``services/admin/provider/model_price_edit``); NULL means no own rate.
    pricing_cache_read = Column(Float, nullable=True)
    pricing_cache_write = Column(Float, nullable=True)
    # Which governed contract owns this model's price (see
    # ``services/model_gateway/cost_contract``). NULL means no gateway contract
    # declared one, so the persisted prices are the only authority.
    cost_source = Column(String(32), nullable=True)
    max_tokens_per_request = Column(Integer, nullable=True)
    rate_limit_rpm = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True, index=True)
    # Model catalog. ``catalog_key`` is the stable key a
    # Workspace or policy names the model by: the gateway alias or the provider model id, prefixed with
    # the provider name only on a collision; ``catalog_key.py`` assigns it on insert.
    catalog_key = Column(String(320), nullable=True, unique=True, index=True)
    # The highest data classification this model is cleared for; NULL = not cleared for any data.
    cleared_up_to = Column(String(30), nullable=True)
    # Content categories (``pci``, ``pii``, ...) the model is approved to receive.
    approved_data_categories = Column(JSON, nullable=True)
    # Explicit capabilities ``{tools, vision, coding, long_context}``; nothing is inferred from the name.
    capabilities_json = Column(JSON, nullable=True)
    # Explicit temperature in [0, 2]; NULL = the provider default.
    temperature = Column(Float, nullable=True)
    # Set by a provider sync that no longer lists a model it listed before ("gone upstream").
    upstream_gone_at = Column(DateTime, nullable=True)

    provider = relationship("LLMProvider", back_populates="models")


class UserProviderToken(Base):
    __tablename__ = "user_provider_tokens"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    provider_id = Column(String(36), ForeignKey("llm_providers.id"), nullable=False)
    encrypted_token = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User")
    provider = relationship("LLMProvider")


from . import catalog_key as _catalog_key  # noqa: E402,F401 - side effect: registers the insert listener
