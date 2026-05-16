#!/usr/bin/env bash
# Runs one backtest per month for the trailing 12 months.
# Results land in user_data/backtest_results/monthly/
# Usage: bash user_data/scripts/run_monthly_backtests.sh [STRATEGY]
# Default strategy: NostalgiaForInfinityX7
#
# Per-month pair filtering:
#   Each month only backtests pairs that have ≥800 4h startup candles before
#   the month's start date. Newer tokens are automatically included once they
#   have enough history, so later months get progressively more pairs.
#
# Data layout:
#   download-data  -> --datadir NostalgiaForInfinity/user_data/data      (creates futures/ inside)
#   backtesting    -> --datadir NostalgiaForInfinity/user_data/data      (freqtrade appends /futures/ itself)

set -euo pipefail

STRATEGY="${1:-NostalgiaForInfinityX7}"
RESULTS_DIR="user_data/backtest_results/monthly"
LOGFILE="${RESULTS_DIR}/run.log"

mkdir -p "$RESULTS_DIR"

CFG_BASE="NostalgiaForInfinity/configs/exampleconfig.json"
CFG_FUTURES="NostalgiaForInfinity/configs/trading_mode-futures.json"
CFG_PAIRS_MASTER="NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json"
DATADIR="NostalgiaForInfinity/user_data/data"

# 12 month windows: Apr 2025 – Apr 2026
MONTHS=(
  "20250401 20250501"
  "20250501 20250601"
  "20250601 20250701"
  "20250701 20250801"
  "20250801 20250901"
  "20250901 20251001"
  "20251001 20251101"
  "20251101 20251201"
  "20251201 20260101"
  "20260101 20260201"
  "20260201 20260301"
  "20260301 20260424"
)

echo "=== Monthly backtest run: $(date) ===" | tee -a "$LOGFILE"
echo "Strategy: $STRATEGY" | tee -a "$LOGFILE"

for PERIOD in "${MONTHS[@]}"; do
  START=$(echo "$PERIOD" | awk '{print $1}')
  END=$(echo   "$PERIOD" | awk '{print $2}')
  LABEL="${START:0:6}"   # e.g. 202504
  OUTFILE="${RESULTS_DIR}/backtest_${STRATEGY}_${LABEL}.zip"

  if [[ -f "$OUTFILE" ]]; then
    echo "[SKIP] $LABEL — result already exists: $OUTFILE" | tee -a "$LOGFILE"
    continue
  fi

  # Build a per-month pairlist: only pairs with ≥800 4h candles (133 days) before START
  # startup_candle_count=800 on 4h = 3200 hours ≈ 133 days
  CFG_PAIRS_MONTH=$(mktemp /tmp/pairlist_month_XXXXXX.json)
  trap 'rm -f "$CFG_PAIRS_MONTH"' RETURN

  python3 - <<PYEOF "$CFG_PAIRS_MASTER" "$START" "$CFG_PAIRS_MONTH"
import json, sys, pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone

master_cfg_path, start_str, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(master_cfg_path) as f:
    cfg = json.load(f)

# Cutoff: 20 days before backtest start (enough for RSI_14 warmup on 4h)
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
if skipped:
    print(f"  Skipped: {', '.join(skipped)}")
PYEOF

  N_PAIRS=$(python3 -c "import json; d=json.load(open('$CFG_PAIRS_MONTH')); print(len(d['exchange']['pair_whitelist']))")
  echo "" | tee -a "$LOGFILE"
  echo "[RUN] $LABEL  timerange ${START}-${END}  (${N_PAIRS} pairs)" | tee -a "$LOGFILE"

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
  trap - RETURN

  if [[ $EXIT_CODE -ne 0 ]]; then
    echo "[ERROR] backtest failed for $LABEL (exit $EXIT_CODE)" | tee -a "$LOGFILE"
    continue
  fi

  # Rename newest zip to predictable name
  NEWEST_ZIP=$(ls -1t "${RESULTS_DIR}"/backtest-result-*.zip 2>/dev/null | head -1 || true)
  if [[ -n "$NEWEST_ZIP" ]]; then
    mv "$NEWEST_ZIP" "$OUTFILE"
    META="${NEWEST_ZIP%.zip}.meta.json"
    [[ -f "$META" ]] && mv "$META" "${OUTFILE%.zip}.meta.json"
    echo "[OK] $LABEL done -> $OUTFILE" | tee -a "$LOGFILE"
  else
    echo "[WARN] $LABEL ran but no zip output found" | tee -a "$LOGFILE"
  fi
done

echo "" | tee -a "$LOGFILE"
echo "=== All months finished: $(date) ===" | tee -a "$LOGFILE"
echo "Run summary: python user_data/scripts/summarize_monthly.py --strategy $STRATEGY"
