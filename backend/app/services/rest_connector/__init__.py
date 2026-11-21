"""Custom REST connector: reads, writes and device calls.

An admin adds an arbitrary REST API without code: a definition imported from OpenAPI (``openapi_reader``) or
entered by hand (``definitions``), a connection per Workspace or platform with base URL and secrets
(``connections``), and per enabled operation a tool ``rest__<definition>__<operation>`` (``tool_surface``).

Octryx is the authorization layer (``authorization``): the API is reached with a technical account, so every call
is checked against the operation's grants (Octryx role, optionally one Workspace) and runs inside the grant's data
scope, injected server-side as structured parameters (never as model-written query text) plus an optional result
filter. ``executor`` runs a call through the pinned ``custom_rest`` egress transport and writes one audit row per
call (``runs``).

A write passes the platform's existing gates, never its own: the run class (``deliver`` unless the admin
says ``change``), the chat's write plan, the central approval gate with the request as its preview (``preview``), and
for devices (``services/mcp_rest_tools``) and unattended runs a person per call (unattended: unless the platform
default allows the tool).

SAP and OData (phase 2b): ``odata`` (response presets, ``$batch`` refused), ``param_names`` (``$filter`` offered as
``filter``), ``op_keys`` (readable keys without ``operationId``) and ``csrf`` (token fetch before a write).
"""
