"""MCP server configuration models."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.redaction_policy import redact_secret_payload


class TransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


@dataclass
class OAuthConfig:
    client_id: str = ""
    client_secret: str = ""
    token_url: str = ""
    authorization_url: str = ""
    scopes: list[str] = field(default_factory=list)
    # Dynamic Client Registration (RFC 7591)
    registration_url: str = ""
    # Cached tokens (populated at runtime)
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: float = 0.0  # Unix timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token_url": self.token_url,
            "authorization_url": self.authorization_url,
            "scopes": self.scopes,
            "registration_url": self.registration_url,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_secret": redact_secret_payload(self.client_secret, key_hint="client_secret"),
            "token_url": self.token_url,
            "authorization_url": self.authorization_url,
            "scopes": self.scopes,
            "registration_url": self.registration_url,
            "has_access_token": bool(self.access_token),
            "has_refresh_token": bool(self.refresh_token),
            "token_expires_at": self.token_expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OAuthConfig":
        return cls(
            client_id=data.get("client_id", ""),
            client_secret=data.get("client_secret", ""),
            token_url=data.get("token_url", ""),
            authorization_url=data.get("authorization_url", ""),
            scopes=data.get("scopes", []),
            registration_url=data.get("registration_url", ""),
        )


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    transport: TransportType = TransportType.STDIO
    url: str | None = None
    auto_start: bool = True
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    oauth: OAuthConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "headers": self.headers,
            "transport": self.transport.value if isinstance(self.transport, TransportType) else self.transport,
            "url": self.url,
            "auto_start": self.auto_start,
            "description": self.description,
            "metadata": self.metadata,
        }
        if self.oauth:
            d["oauth"] = self.oauth.to_dict()
        return d

    def to_public_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": redact_secret_payload(self.env, max_string_length=240),
            "headers": redact_secret_payload(self.headers, max_string_length=240),
            "transport": self.transport.value if isinstance(self.transport, TransportType) else self.transport,
            "url": self.url,
            "auto_start": self.auto_start,
            "description": self.description,
            "metadata": redact_secret_payload(self.metadata, max_string_length=240),
        }
        if self.oauth:
            d["oauth"] = self.oauth.to_public_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerConfig":
        transport = data.get("transport", "stdio")
        if isinstance(transport, str):
            transport = TransportType(transport)
        oauth = None
        if "oauth" in data and data["oauth"]:
            oauth = OAuthConfig.from_dict(data["oauth"])
        return cls(
            name=data["name"],
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env", {}),
            headers=data.get("headers", {}),
            transport=transport,
            url=data.get("url"),
            auto_start=data.get("auto_start", True),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
            oauth=oauth,
        )


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
    server_id: str

@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str | None
    server_name: str
    server_id: str


@dataclass
class MCPPrompt:
    name: str
    description: str
    arguments: list[dict[str, Any]]
    server_name: str
    server_id: str
