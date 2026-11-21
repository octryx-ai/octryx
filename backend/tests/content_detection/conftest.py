"""Fixtures of the gateway harnesses the content-routing tests reuse."""

from tests.agent_gateway.seat_upstream_support import anthropic  # noqa: F401 - the seat route's fake upstream
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - the governed route
