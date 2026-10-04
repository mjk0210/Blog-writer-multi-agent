#!/usr/bin/env bash
# Link this repo's agent workspaces into ~/.openclaw and install the config.
set -euo pipefail

OC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"

mkdir -p "$STATE_DIR"

for ws in "$OC_DIR"/workspaces/*/; do
  id="$(basename "$ws")"
  target="$STATE_DIR/workspace-$id"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skip $target (exists and is not a symlink)"
    continue
  fi
  ln -sfn "$ws" "$target"
  echo "linked $target -> $ws"
done

if [ -e "$CONFIG" ]; then
  # Merges objects recursively; arrays (agents.list) are replaced, so review the diff first.
  openclaw config patch --file "$OC_DIR/openclaw.json5" --dry-run
  read -r -p "apply this patch to $CONFIG? [y/N] " ok
  if [ "$ok" = "y" ]; then
    openclaw config patch --file "$OC_DIR/openclaw.json5"
  fi
else
  cp "$OC_DIR/openclaw.json5" "$CONFIG"
  echo "installed config at $CONFIG"
fi

if [ ! -e "$STATE_DIR/.env" ]; then
  cp "$OC_DIR/.env.example" "$STATE_DIR/.env"
  echo "created $STATE_DIR/.env; fill in GEMINI_API_KEY and OPENCLAW_GATEWAY_TOKEN"
fi

echo "next: openclaw doctor && openclaw gateway restart && openclaw agents list"
