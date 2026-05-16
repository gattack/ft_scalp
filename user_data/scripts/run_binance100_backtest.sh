#!/usr/bin/env bash
# Runs monthly backtests Jan 2024 – Apr 2026 using Binance top-100 pairlist.
# Results go to user_data/backtest_results/binance100/
# Usage: bash user_data/scripts/run_binance100_backtest.sh [STRATEGY]

set -euo pipefail

STRATEGY="${1:-NostalgiaScalpPro}"
RESULTS_DIR="user_data/backtest_results/binance100"
LOGFILE="${RESULTS_DIR}/run_binance100_${STRATEGY}.log"
mkdir -p "$RESULTS_DIR"

CFG_BASE="NostalgiaForInfinity/configs/exampleconfig.json"
CFG_FUTURES="NostalgiaForInfinity/configs/trading_mode-futures.json"
CFG_PAIRS_MASTER="NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-top100.json"
DATADIR="NostalgiaForInfinity/user_data/data"

MONTHS=(
  "20240101 20240201"
  "20240201 20240301"
  "20240301 20240401"
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
  "20260301 20260401"
  "20260401 20260501"
  "20260501 20260516"
)

for MONTH_RANGE in "${MONTHS[@]}"; do
  START=$(echo "$MONTH_RANGE" | awk '{print $1}')
  END=$(echo "$MONTH_RANGE" | awk '{print $2}')
  LABEL="${START:0:6}"
  OUTFILE="$RESULTS_DIR/backtest_${STRATEGY}_${LABEL}.zip"

  if [ -f "$OUTFILE" ]; then
    echo "SKIPPING $LABEL (already done)"
    continue
  fi

  FILTERED_JSON=$(python3 - "$CFG_PAIRS_MASTER" "$START" "$DATADIR/futures" << 'PYEOF'
import json, os, sys, tempfile
from datetime import datetime, timedelta
import pandas as pd

cfg_path, start_str, datadir = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(cfg_path))
pairs = d["exchange"]["pair_whitelist"]
start_dt = datetime.strptime(start_str, "%Y%m%d")
cutoff = start_dt - timedelta(days=20)

kept = []
for p in pairs:
    sym = p.replace("/", "_").replace(":", "_")
    f4h = os.path.join(datadir, sym + "-4h-futures.feather")
    if not os.path.exists(f4h):
        continue
    df = pd.read_feather(f4h)
    if df.empty:
        continue
    first = pd.to_datetime(df["date"].iloc[0])
    if first.tz_localize(None) <= cutoff:
        kept.append(p)

d["exchange"]["pair_whitelist"] = kept
tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump(d, tmp)
tmp.flush()
print(tmp.name)
print(f"  {len(kept)} pairs kept, {len(pairs)-len(kept)} skipped", file=sys.stderr)
PYEOF
)

  echo "Month $LABEL: running..." | tee -a "$LOGFILE"

  freqtrade backtesting \
    --config "$CFG_BASE" \
    --config "$CFG_FUTURES" \
    --config "$FILTERED_JSON" \
    --strategy "$STRATEGY" \
    --strategy-path user_data/strategies \
    --timerange "${START}-${END}" \
    --datadir "$DATADIR" \
    --export trades \
    --backtest-directory "$RESULTS_DIR" \
    --cache day \
    --notes "${STRATEGY}_binance100_${LABEL}" \
    2>&1 | tee -a "$LOGFILE" | grep -E "Total profit|Result for|Backtesting with"

  ZIP=$(ls -t "$RESULTS_DIR"/backtest-result-*.zip 2>/dev/null | head -1 || true)
  if [ -n "$ZIP" ]; then
    mv "$ZIP" "$OUTFILE"
    META="${ZIP%.zip}.meta.json"
    [ -f "$META" ] && mv "$META" "${OUTFILE%.zip}.meta.json"
    echo "[OK] $LABEL -> $OUTFILE" | tee -a "$LOGFILE"
  else
    echo "[WARN] No zip produced for $LABEL" | tee -a "$LOGFILE"
  fi

  rm -f "$FILTERED_JSON"
done

echo "Done. Results in $RESULTS_DIR" | tee -a "$LOGFILE"
