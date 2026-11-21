"""Runtime helpers extracted from ``app.web._context``."""


__all__ = [
    "_MCP_CATALOG",
]

# Only servers the platform can reach from its API pod: remote (streamable HTTP / SSE). The stdio presets
# (Cloudflare via npx mcp-remote, Azure via npx, AWS Documentation via uvx, Terraform via docker) never ran there:
# the API image ships no Node, uv or Docker, and Docker in a pod is not an option. A
# stdio server can still be configured where its executable is installed (``client.resolve_stdio_command``).
_MCP_CATALOG = {
    "context7": {
        "slug": "context7",
        "name": "Context7",
        "vendor": "Upstash",
        "description": "Up-to-date library and framework documentation via the official Context7 MCP server.",
        "source_url": "https://github.com/upstash/context7#installation",
        "transport": "streamable-http",
        "command": "",
        "args": [],
        "url": "https://mcp.context7.com/mcp",
        "auto_start": True,
        "default_name": "context7",
        "fields": [
            {
                "name": "context7_api_key",
                "label": "Context7 API key",
                "type": "password",
                "required": True,
                "placeholder": "Required for the remote Context7 MCP service",
                "header": "CONTEXT7_API_KEY",
                "header_aliases": ["Context7-API-Key"],
            }
        ],
    },
    "aws-knowledge": {
        "slug": "aws-knowledge",
        "name": "AWS Knowledge MCP",
        "vendor": "AWS",
        "description": "Official AWS remote MCP server for AWS knowledge lookups.",
        "source_url": "https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server",
        "transport": "streamable-http",
        "url": "https://knowledge-mcp.global.api.aws",
        "auto_start": True,
        "default_name": "aws-knowledge-mcp-server",
        "fields": [],
    },
}
