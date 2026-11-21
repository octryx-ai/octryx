"""The Octryx pet: a tray icon that shows what needs the person (Octryx companion, stage 2; macOS first).

- ``model``: the platform's pet state (``GET /api/v1/agent-gateway/pet``, contract ``pet_v1``) parsed, never raising;
- ``schedule``: when to ask again (the server's hint, defaults, backoff);
- ``settings``: the person's own pet settings (quiet hours, notifications), no quiet hours by default;
- ``display``: what the icon, tooltip, menu and notifications show (pure);
- ``icons``: the mascot with a state badge, per appearance;
- ``api``: the HTTP read with ETag; ``runner``: the poll loop; ``tray``: pystray glue; ``service``: autostart.

pystray and Pillow are the ``pet`` extra (``octryx-claude[pet]``); only ``icons`` and ``tray`` import them.
"""
