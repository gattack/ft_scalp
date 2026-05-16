#!/usr/bin/env bash
# Runs monthly backtests for Apr 2024 – Mar 2025 (the prior year not yet covered).
# Usage: bash user_data/scripts/run_2024_backtests.sh [STRATEGY]
# Runs X7 first, then NostalgiaCombinedFast if no arg given.

set -euo pipefail

RESULTS_DIR="user_data/backtest_results/monthly"
LOGFILE="${RESULTS_DIR}/run_2024.log"

mkdir -p "$RESULTS_DIR"

CFG_BASE="NostalgiaForInfinity/configs/exampleconfig.json"
CFG_FUTURES="NostalgiaForInfinity/configs/trading_mode-futures.json"
CFG_PAIRS_MASTER="NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json"
DATADIR="NostalgiaForInfinity/user_data/data"

MONTHS=(
  "20240401 20240501"
  "20240501 20240601"
  "20240601 20240701"
  "20240701 20240801"
  "20240801 20240901"
  "20240901 20241001"
  "20241001 20241101"
  "20241101 20241201"
  "20241201 20250101"
  "20250101 20250201"
  "20250201 20250301"
  "20250301 20250401"
)

run_strategy() {
  local STRATEGY="$1"
  echo "" | tee -a "$LOGFILE"
  echo "=== Strategy: $STRATEGY  $(date) ===" | tee -a "$LOGFILE"

  for PERIOD in "${MONTHS[@]}"; do
    START=$(echo "$PERIOD" | awk '{print $1}')
    END=$(echo   "$PERIOD" | awk '{print $2}')
    LABEL="${START:0:6}"
    OUTFILE="${RESULTS_DIR}/backtest_${STRATEGY}_${LABEL}.zip"

    if [[ -f "$OUTFILE" ]]; then
      echo "[SKIP] $LABEL — already exists" | tee -a "$LOGFILE"
      continue
    fi

    CFG_PAIRS_MONTH=$(mktemp /tmp/pairlist_month_XXXXXX.json)

    python3 - <<PYEOF "$CFG_PAIRS_MASTER" "$START" "$CFG_PAIRS_MONTH"
import json, sys, pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

master_cfg_path, start_str, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(master_cfg_path) as f:
    cfg = json.load(f)

start_dt = datetime.strptime(start_str, "%Y%m%d").replace(tzinfo=timezone.utc)
cutoff = start_dt - timedelta(days=20)

data_dir = Path("NostalgiaForInfinity/user_data/data/futures")
good = []
skipped = []
for pair in cfg["exchange"]["pair_whitelist"]:
    base = pair.split("/")[0]
    fname = f"{base}_USDT_USDT-4h-futures.feather"
    p = data_dir / fname
    if not p.exists():
        skipped.append(f"{pair}(no file)")
        continue
    df = pd.read_feather(p)
    if len(df) == 0:
        skipped.append(f"{pair}(empty)")
        continue
    earliest = pd.to_datetime(df["date"].min())
    if earliest.tz is None:
        earliest = earliest.tz_localize("UTC")
    if earliest <= cutoff:
        good.append(pair)
    else:
        skipped.append(f"{pair}(starts {earliest.date()})")

cfg["exchange"]["pair_whitelist"] = good
with open(out_path, "w") as f:
    json.dump(cfg, f, indent=2)

print(f"Month {start_str}: {len(good)} pairs kept, {len(skipped)} skipped")
PYEOF

    N_PAIRS=$(python3 -c "import json; d=json.load(open('$CFG_PAIRS_MONTH')); print(len(d['exchange']['pair_whitelist']))")
    echo "[RUN] $LABEL  ${START}-${END}  (${N_PAIRS} pairs)" | tee -a "$LOGFILE"

    freqtrade backtesting \
      --config "$CFG_BASE" \
      --config "$CFG_FUTURES" \
      --config "$CFG_PAIRS_MONTH" \
      --strategy "$STRATEGY" \
      --strategy-path user_data/strategies \
      --timerange "${START}-${END}" \
      --datadir "$DATADIR" \
      --export trades \
      --backtest-directory "$RESULTS_DIR" \
      --notes "${STRATEGY}_${LABEL}" \
      2>&1 | tee -a "$LOGFILE"

    EXIT_CODE=${PIPESTATUS[0]}
    rm -f "$CFG_PAIRS_MONTH"

    if [[ $EXIT_CODE -ne 0 ]]; then
      echo "[ERROR] backtest failed for $LABEL (exit $EXIT_CODE)" | tee -a "$LOGFILE"
      continue
    fi

    NEWEST_ZIP=$(ls -1t "${RESULTS_DIR}"/backtest-result-*.zip 2>/dev/null | head -1 || true)
    if [[ -n "$NEWEST_ZIP" ]]; then
      mv "$NEWEST_ZIP" "$OUTFILE"
      META="${NEWEST_ZIP%.zip}.meta.json"
      [[ -f "$META" ]] && mv "$META" "${OUTFILE%.zip}.meta.json"
      echo "[OK] $LABEL -> $OUTFILE" | tee -a "$LOGFILE"
    else
      echo "[WARN] $LABEL: no zip output found" | tee -a "$LOGFILE"
    fi
  done
}

STRATEGIES=("${@:-NostalgiaForInfinityX7 NostalgiaCombinedFast}")
if [[ $# -eq 0 ]]; then
  run_strategy "NostalgiaForInfinityX7"
  run_strategy "NostalgiaCombinedFast"
else
  for S in "$@"; do
    run_strategy "$S"
  done
fi

echo "" | tee -a "$LOGFILE"
echo "=== 2024 backtests done: $(date) ===" | tee -a "$LOGFILE"
