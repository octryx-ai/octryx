from __future__ import annotations

import ipaddress
from typing import get_args

import pytest

from app.services import outbound_url_policy as url_policy
from app.services.outbound_egress.connections import CONNECTIONS, connection_rule
from app.services.outbound_url_types import AddressClass, EgressScope


def test_every_egress_connection_rule_has_a_closed_scope():
    assert {connection_rule(name).scope for name in CONNECTIONS} <= set(get_args(EgressScope))


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.1.2.3", "8.8.8.8", "::ffff:10.0.0.1", "::1"])
def test_every_address_class_is_closed(address):
    assert url_policy.classify_address(ipaddress.ip_address(address)) in get_args(AddressClass)




