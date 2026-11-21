"""Where a seat session's model traffic leaves: from the device or from the server.

A cluster with restricted egress cannot reach ``chatgpt.com``, so a Codex seat turn sent from the server fails
``codex_turn_failed``. The platform switch ``agent_gateway.seat_traffic`` (``SystemConfig``, platform admins only):

- ``device`` (default): **the server admits, the device sends.** The launcher runs a loopback seat proxy per job; for
  each call it asks the server to admit the body (``/openai/seat/admit``: exactly the seat route's checks), sends the
  admitted body to ChatGPT itself with the person's own login, and reports the answer (``/openai/seat/report``), which
  the server records like the route does (``model_gateway.inbound.codex_seat_device``);
- ``gateway``: the server relays the call (``/openai/seat/responses``).

The switch decides both ways and is never changed automatically: in ``device`` mode the relay route refuses
(``codex_seat_traffic_device``), in ``gateway`` mode admit refuses (``codex_seat_traffic_gateway``; a ticket admitted
before the switch is still reported and recorded); the launcher never falls back from one to the other on an error.
It governs the Codex seat now; the Claude seat stays on the gateway until it gets the same admit/report pair.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig

SEAT_TRAFFIC_KEY = "agent_gateway.seat_traffic"
SEAT_TRAFFIC_DEVICE = "device"
SEAT_TRAFFIC_GATEWAY = "gateway"
SEAT_TRAFFIC_MODES = (SEAT_TRAFFIC_DEVICE, SEAT_TRAFFIC_GATEWAY)
DEFAULT_SEAT_TRAFFIC = SEAT_TRAFFIC_DEVICE
AUDIT_SEAT_TRAFFIC = "admin.agent_gateway.seat_traffic_updated"
REASON_TRAFFIC_DEVICE = "codex_seat_traffic_device"
REASON_TRAFFIC_GATEWAY = "codex_seat_traffic_gateway"


async def seat_traffic(db: AsyncSession) -> str:
    """``device`` unless a platform admin stored ``gateway``."""
    row = await db.get(SystemConfig, SEAT_TRAFFIC_KEY)
    value = str(row.value or "").strip().lower() if row is not None else ""
    return value if value in SEAT_TRAFFIC_MODES else DEFAULT_SEAT_TRAFFIC


async def set_seat_traffic(db: AsyncSession, *, value: object, actor_id: str) -> str:
    if value not in SEAT_TRAFFIC_MODES:
        raise ValueError("seat_traffic must be device or gateway")
    before = await seat_traffic(db)
    row = await db.get(SystemConfig, SEAT_TRAFFIC_KEY)
    if row is None:
        row = SystemConfig(key=SEAT_TRAFFIC_KEY,
                           description="Where seat model traffic leaves: device (the launcher) or gateway (the server)")
        db.add(row)
    row.value = str(value)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_SEAT_TRAFFIC, resource_type="system_config",
                    resource_id=SEAT_TRAFFIC_KEY, details={"before": before, "after": value}))
    await db.flush()
    return str(value)


__all__ = [
    "AUDIT_SEAT_TRAFFIC",
    "DEFAULT_SEAT_TRAFFIC",
    "REASON_TRAFFIC_DEVICE",
    "REASON_TRAFFIC_GATEWAY",
    "SEAT_TRAFFIC_DEVICE",
    "SEAT_TRAFFIC_GATEWAY",
    "SEAT_TRAFFIC_KEY",
    "SEAT_TRAFFIC_MODES",
    "seat_traffic",
    "set_seat_traffic",
]
