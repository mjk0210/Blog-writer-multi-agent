#!/usr/bin/env bash
# Add the BlogGPT and task-routed agents to an existing OpenClaw (2026.9+) install.
#
# - links this repo's agent workspaces into ~/.openclaw
# - merges openclaw.json5 into your config with `openclaw config patch`
#   (keeps your other agents, channels and gateway settings; backs up first)
# - appends the delegation rules to the main agent's AGENTS.md (once)
#
# Usage: openclaw/scripts/install.sh [--yes]
# Model overrides (optional): GENERAL_MODEL FLASH_MODEL CODING_MODEL COMPLEX_MODEL WRITING_MODEL
set -euo pipefail

OC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"
ASSUME_YES=0
[ "${1:-}" = "--yes" ] && ASSUME_YES=1

command -v openclaw >/dev/null || { echo "openclaw not found on PATH" >&2; exit 1; }

# agents.entries and tools.alsoAllow need 2026.9 or later.
version="$(openclaw --version 2>/dev/null | grep -oE '[0-9]{4}\.[0-9]+' | head -1)"
year="${version%%.*}"; month="${version#*.}"
if [ -z "$version" ] || [ "$year" -lt 2026 ] || { [ "$year" -eq 2026 ] && [ "$month" -lt 9 ]; }; then
  echo "OpenClaw $version found; this setup needs 2026.9 or later (npm i -g openclaw@latest)" >&2
  exit 1
fi

if [ ! -e "$CONFIG" ]; then
  echo "No config at $CONFIG. Run 'openclaw onboard' first, then re-run this script." >&2
  exit 1
fi

if ! openclaw config validate >/dev/null 2>&1; then
  echo "Your current config does not validate. Run 'openclaw doctor --fix' first:" >&2
  openclaw config validate >&2 || true
  exit 1
fi

backup="$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"
cp "$CONFIG" "$backup"
echo "backed up config to $backup"

# 1. Workspaces
for ws in "$OC_DIR"/workspaces/*/; do
  id="$(basename "$ws")"
  target="$STATE_DIR/workspace-$id"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skip $target (a real directory already exists; remove it to use the repo version)"
    continue
  fi
  ln -sfn "$ws" "$target"
  echo "linked $target"
done

# 2. Config patch, with optional model overrides
patch_file="$(mktemp --suffix=.json5)"
trap 'rm -f "$patch_file"' EXIT
sed \
  -e "s#openrouter/minimax/minimax-m3#${GENERAL_MODEL:-openrouter/minimax/minimax-m3}#g" \
  -e "s#openrouter/google/gemini-3-flash-preview#${FLASH_MODEL:-openrouter/google/gemini-3-flash-preview}#g" \
  -e "s#openrouter/deepseek/deepseek-v4-pro#${CODING_MODEL:-openrouter/deepseek/deepseek-v4-pro}#g" \
  -e "s#openrouter/anthropic/claude-opus-5-5#${COMPLEX_MODEL:-openrouter/anthropic/claude-opus-5-5}#g" \
  -e "s#openrouter/anthropic/claude-sonnet-5-5#${WRITING_MODEL:-openrouter/anthropic/claude-sonnet-5-5}#g" \
  "$OC_DIR/openclaw.json5" > "$patch_file"

openclaw config patch --file "$patch_file" --dry-run
if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "apply this patch to $CONFIG? [y/N] " ok
  [ "$ok" = "y" ] || { echo "not applied"; exit 0; }
fi
openclaw config patch --file "$patch_file"

# 3. Delegation rules for the main agent (appended once)
main_ws="$(openclaw config get agents.entries.main.workspace --json 2>/dev/null | sed -n 's/^"\(.*\)"$/\1/p')"
main_ws="${main_ws:-$STATE_DIR/workspace}"
main_ws="${main_ws/#\~/$HOME}"
mkdir -p "$main_ws"
if grep -qs "blog-writer-multi-agent:delegation" "$main_ws/AGENTS.md"; then
  echo "delegation rules already in $main_ws/AGENTS.md"
else
  cat "$OC_DIR/main-delegation.md" >> "$main_ws/AGENTS.md"
  echo "added delegation rules to $main_ws/AGENTS.md"
fi

openclaw config validate
cat <<EOF

Done. Next:
  1. Put OPENROUTER_API_KEY=sk-or-... in $STATE_DIR/.env (if not already there)
  2. openclaw gateway restart   (on a Pi, startup can take over a minute)
  3. openclaw agents list
  4. openclaw agent --agent blog-coordinator --timeout 900 -m "Write a blog post about <topic>"
To undo: cp "$backup" "$CONFIG" && openclaw gateway restart
EOF
