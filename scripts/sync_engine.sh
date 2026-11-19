#!/usr/bin/env bash
set -euo pipefail
source_repo="${1:?Usage: scripts/sync_engine.sh /path/to/tamid-quant-nyu}"
for strategy in btc-kalshi-digital kalshi-multi-tail; do
  mkdir -p "engine/$strategy"
  rsync -a --exclude tests --exclude '*.png' --exclude __pycache__ "$source_repo/strategies/$strategy/" "engine/$strategy/"
done
git -C "$source_repo" rev-parse HEAD > engine/SOURCE_COMMIT
