"""The closed scopes of the outbound URL policy and the address classes it sorts resolved addresses into."""

from typing import Literal

EgressScope = Literal["public_only", "no_pod_local"]
AddressClass = Literal["pod_local", "private", "public"]

__all__ = ["AddressClass", "EgressScope"]
