#!/usr/bin/env python3
"""Check Azure Bot registration calling webhook configuration."""
import json
import os
import sqlite3
import urllib.parse
import urllib.request

# Read app credentials from DB
conn = sqlite3.connect(os.environ.get("OCTRYX_DB", "data/octryx.db"))  # the local SQLite database
row = conn.execute("SELECT config FROM channel_configs WHERE id = 2").fetchone()
config = json.loads(row[0])
app_id = config["app_id"]
app_password = config["app_password"]
tenant_id = config["tenant_id"]
print(f"App ID: {app_id}")
print(f"Tenant: {tenant_id}")

# Get token
data = urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": app_id,
    "client_secret": app_password,
    "scope": "https://graph.microsoft.com/.default",
}).encode()
req = urllib.request.Request(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data=data,
)
resp = urllib.request.urlopen(req)
token = json.loads(resp.read())["access_token"]
print("Got Graph token")

# Check current bot/application registration
filter_str = f"appId eq '{app_id}'"
url = f"https://graph.microsoft.com/v1.0/applications?$filter={urllib.parse.quote(filter_str)}"
req2 = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
try:
    resp2 = urllib.request.urlopen(req2)
    apps = json.loads(resp2.read())
    for app in apps.get("value", []):
        print(f"\nApp: {app.get('displayName')} (id={app.get('id')})")
        print(f"  appId: {app.get('appId')}")
        # Check web.redirectUris and other settings
        web = app.get("web", {})
        print(f"  web.homePageUrl: {web.get('homePageUrl')}")
        print(f"  web.redirectUris: {web.get('redirectUris')}")
        # The calling webhook is typically in the bot channel registration, not the app itself
except Exception as e:
    print(f"Error querying applications: {e}")

# Check Bot Service registration via Bot Framework API
# The calling webhook URL is configured in the Azure Bot Service channel settings
# We can try to get it via the Azure Resource Manager API
print("\n--- Checking Bot Framework Service ---")
# Try to get BotService info (requires Azure Management token)
mgmt_data = urllib.parse.urlencode({
    "grant_type": "client_credentials",
    "client_id": app_id,
    "client_secret": app_password,
    "scope": "https://management.azure.com/.default",
}).encode()
req3 = urllib.request.Request(
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    data=mgmt_data,
)
try:
    resp3 = urllib.request.urlopen(req3)
    mgmt_token = json.loads(resp3.read())["access_token"]
    print("Got Azure Management token")
    # The calling webhook is in the bot's MS Teams channel settings
    # but we'd need the subscription ID and resource group to query it
    print("(Calling webhook must be set in Azure Portal > Bot Service > Channels > Teams > Calling)")
except Exception as e:
    print(f"Could not get management token: {e}")
    print("This is expected for app-only credentials without Azure Management scope")
