#!/bin/sh
# Installs (or removes) the daily `cartometa-carmeta sync` on macOS.
#
#   scripts/install-carmeta-sync.sh             install or update
#   scripts/install-carmeta-sync.sh --uninstall remove
#
# The job only ever writes under data/cache/carmeta/ and logs/: it can run
# while you work on any branch.
set -eu

LABEL="com.cartometa.carmeta-sync"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

UV="$(command -v uv)" || { echo "uv not found in PATH: install it first." >&2; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
sed -e "s|__REPO__|$REPO|g" -e "s|__UV__|$UV|g" "$REPO/scripts/carmeta-sync.plist" > "$PLIST"
launchctl bootstrap "$DOMAIN" "$PLIST"

echo "Installed $LABEL: every day at 09:00, from $REPO."
echo "Run it now:   launchctl kickstart $DOMAIN/$LABEL"
echo "Its trace:    $REPO/logs/carmeta-sync.log"
