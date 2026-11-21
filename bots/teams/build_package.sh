#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build the Microsoft Teams App Package (.zip) for the Octryx bot.
# Run:  bash build_package.sh
# ---------------------------------------------------------------------------
set -euo pipefail

MANIFEST_DIR="manifest"

# ------------------------------------------------------------------ icons check
for icon in color.png outline.png; do
    if [ ! -f "$MANIFEST_DIR/$icon" ]; then
        echo "ERROR: Missing icon: $MANIFEST_DIR/$icon"
        echo "       Run:  python generate_icons.py"
        exit 1
    fi
done

# ------------------------------------------------------------------ interactive input
echo ""
echo "================================================"
echo "  Octryx – Teams App Package Builder"
echo "================================================"
echo ""

# BOT_NAME — default: Octryx
read -r -p "Bot name shown in Teams [Octryx]: " BOT_NAME
BOT_NAME="${BOT_NAME:-Octryx}"

# AZURE_APP_ID — required
while true; do
    read -r -p "Azure App ID (Client ID): " AZURE_APP_ID
    if [ -n "$AZURE_APP_ID" ]; then
        break
    fi
    echo "  ✗  App ID cannot be empty."
done

# OCTRYX_HOSTNAME — required, strip https:// prefix if pasted
while true; do
    read -r -p "Octryx hostname (e.g. octryx.example.com or a tunnel host): " OCTRYX_HOSTNAME
    OCTRYX_HOSTNAME="${OCTRYX_HOSTNAME#https://}"
    OCTRYX_HOSTNAME="${OCTRYX_HOSTNAME#http://}"
    OCTRYX_HOSTNAME="${OCTRYX_HOSTNAME%/}"
    if [ -n "$OCTRYX_HOSTNAME" ]; then
        break
    fi
    echo "  ✗  Hostname cannot be empty."
done

# OUTPUT filename — default based on bot name (lowercase, spaces → dashes)
DEFAULT_OUTPUT="$(echo "$BOT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')-teams-bot.zip"
read -r -p "Output filename [$DEFAULT_OUTPUT]: " OUTPUT
OUTPUT="${OUTPUT:-$DEFAULT_OUTPUT}"

# ------------------------------------------------------------------ confirm
echo ""
echo "  Bot name : $BOT_NAME"
echo "  App ID   : $AZURE_APP_ID"
echo "  Endpoint : https://$OCTRYX_HOSTNAME/api/v1/channels/msteams/<channel_id>/webhook"
echo "  Output   : $OUTPUT"
echo ""
read -r -p "Build package? [Y/n]: " CONFIRM
CONFIRM="${CONFIRM:-Y}"
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ------------------------------------------------------------------ build
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

sed \
    -e "s/{{AZURE_APP_ID}}/$AZURE_APP_ID/g" \
    -e "s/{{OCTRYX_HOSTNAME}}/$OCTRYX_HOSTNAME/g" \
    -e "s/{{BOT_NAME}}/$BOT_NAME/g" \
    "$MANIFEST_DIR/manifest.json" > "$WORK_DIR/manifest.json"

cp "$MANIFEST_DIR/color.png"   "$WORK_DIR/"
cp "$MANIFEST_DIR/outline.png" "$WORK_DIR/"

rm -f "$OUTPUT"
(cd "$WORK_DIR" && zip -j - manifest.json color.png outline.png) > "$OUTPUT"

echo ""
echo "✓  Package built: $OUTPUT"
echo ""
echo "Next steps:"
echo "  1. Upload $OUTPUT in Teams → Apps → Upload a custom app"
echo "  2. Set Azure Bot Messaging Endpoint to:"
echo "       https://$OCTRYX_HOSTNAME/api/v1/channels/msteams/<channel_id>/webhook"
echo "  3. Configure the Microsoft Teams channel in Octryx"
echo "     with your App ID and App Password."
