#!/usr/bin/env bash
# Vendor the Kalshi tail engine from tamid-quant-nyu at one commit.
# Copies only git-tracked files at that commit, never the working tree, so untracked local outputs never leak in
# and engine/SOURCE_COMMIT always names exactly what was copied.
set -euo pipefail
source_repo="${1:?Usage: scripts/sync_engine.sh /path/to/tamid-quant-nyu [ref, default origin/main]}"
ref="${2:-origin/main}"
prefix="strategies/kalshi-tails"
here="$(cd "$(dirname "$0")/.." && pwd)"
commit="$(git -C "$source_repo" rev-parse --verify "$ref^{commit}")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git -C "$source_repo" archive "$commit" "$prefix/btc-kalshi-digital" "$prefix/kalshi-multi-tail" | tar -x -C "$tmp"
for strategy in btc-kalshi-digital kalshi-multi-tail; do
  src="$tmp/$prefix/$strategy"
  [ -d "$src" ] || { echo "missing $prefix/$strategy at $commit" >&2; exit 1; }
  mkdir -p "$here/engine/$strategy"
  # The Streamlit dashboard is a local tool; the web app replaces it.
  rsync -a --delete --exclude tests --exclude '*.png' --exclude __pycache__ --exclude dashboard \
    "$src/" "$here/engine/$strategy/"
done
echo "$commit" > "$here/engine/SOURCE_COMMIT"
echo "Synced engine from $commit"
