# Octryx in Microsoft Teams

Octryx answers in Teams through its `msteams` channel. The bot is not a separate service: Octryx receives the Bot
Framework webhook itself and replies through the Bot Framework Connector API. Calls (audio) go through the optional
.NET MediaBridge in `mediabridge/`.

```
Microsoft Teams ──HTTPS (Bot Framework JWT)──▶ Azure Bot ──▶ https://<your-host>/api/v1/channels/msteams/<channel_id>/webhook
                                                                │  backend/app/api/routes/channels.py
                                                                │  backend/app/plugins/channels/teams_plugin.py
Microsoft Teams ◀──────────── Bot Framework Connector API ──────┘
```

## Files

| Path | What it is |
|---|---|
| `manifest/manifest.json` | Teams app manifest with the placeholders `{{AZURE_APP_ID}}`, `{{OCTRYX_HOSTNAME}}`, `{{BOT_NAME}}` |
| `manifest/color.png`, `manifest/outline.png` | Placeholder icons (192×192 and 32×32); `python generate_icons.py` regenerates them |
| `build_package.sh` | Builds the Teams app package (`.zip`) from the manifest; asks for the values, writes nothing else |
| `dev/` | Local development without Azure or Teams: a mock Bot Framework server and a test sender |
| `mediabridge/` | .NET service for Teams calls: streams call audio to Octryx and plays its answers |

No app package is committed: it contains your Azure app ID and host, so build it yourself.

## Set up

1. **Register an Azure Bot** (multi-tenant) and note its App ID and client secret.
2. **Configure the channel in Octryx**: add a Microsoft Teams channel with the App ID, the client secret
   (`app_password`) and `tenant_id`. Its channel ID is shown in the channel list.
3. **Set the Azure Bot's messaging endpoint** to `https://<your-host>/api/v1/channels/msteams/<channel_id>/webhook`.
   Octryx must be reachable over HTTPS on port 443.
4. **Build and upload the app package**:
   ```bash
   cd bots/teams
   bash build_package.sh   # asks for the bot name, the Azure App ID and <your-host>
   ```
   Upload the resulting `.zip` in Teams under Apps → Manage your apps → Upload an app.

Every webhook is authenticated with the Bot Framework (or Graph calling) JWT.

## Local development

No Azure account and no Teams are needed:

1. Run the backend locally (`uvicorn app.main:app --reload --no-proxy-headers` in `backend/`) with a Teams channel
   that has `dev_mode: true` (see `dev/dev_channel_config.json`). `dev_mode` only skips the Azure token fetch; it is
   for local development only.
2. Start the mock Bot Framework server, which prints what Octryx would send to Teams:
   `python bots/teams/dev/mock_bf_server.py` (needs `aiohttp`).
3. Send a message: `python bots/teams/dev/send_test_message.py --channel-id <channel_id> "Your question"` (needs
   `httpx`; `--help` lists the options).

A webhook without a JWT is accepted only with `OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED=true`, which the backend
refuses to start with unless `DEBUG=true`, a non-production runtime profile and loopback-only CORS origins are set.

## Calls (MediaBridge)

`mediabridge/` streams the audio of a Teams call to Octryx at
`wss://<your-host>/api/v1/teams/calls/<call_id>/audio/ws` and plays the answers back. The one setting it reads is
`Octryx:AudioWsBaseUrl` in `mediabridge/appsettings.json` (or the matching environment variable):
`wss://<your-host>/api/v1/teams/calls`. For a local test, any HTTPS tunnel to your machine works as `<your-host>`.
