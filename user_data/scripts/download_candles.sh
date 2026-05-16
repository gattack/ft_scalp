#!/usr/bin/env bash
# Download candle data for top N crypto-only Binance futures pairs by volume.
# Excludes commodities (gold, silver, oil, gas), stocks, and garbage tokens.
#
# Usage: bash user_data/scripts/download_candles.sh [N_PAIRS] [TIMERANGE]
# Examples:
#   bash user_data/scripts/download_candles.sh          # top 90, last 5 years
#   bash user_data/scripts/download_candles.sh 50       # top 50, last 5 years
#   bash user_data/scripts/download_candles.sh 90 20230101-
#
# Data lands in: NostalgiaForInfinity/user_data/data/binance/futures/
# For backtesting use: --datadir NostalgiaForInfinity/user_data/data/binance

set -euo pipefail

N_PAIRS="${1:-90}"
TIMERANGE="${2:-20210101-}"   # 5 years of history
DATADIR="NostalgiaForInfinity/user_data/data"
TIMEFRAMES="5m 15m 1h 4h 1d"

CFG_BASE="NostalgiaForInfinity/configs/exampleconfig.json"
CFG_FUTURES="NostalgiaForInfinity/configs/trading_mode-futures.json"
PAIRLIST_OUT="NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json"

# Fetch 2x candidates to have headroom after filtering
FETCH_N=$(( N_PAIRS * 2 ))

VOLUME_CFG=$(mktemp /tmp/volume_pairlist_XXXXXX.json)
RAW_JSON_FILE=$(mktemp /tmp/raw_pairs_XXXXXX.json)
trap 'rm -f "$VOLUME_CFG" "$RAW_JSON_FILE"' EXIT

cat > "$VOLUME_CFG" << EOF
{
  "stake_currency": "USDT",
  "exchange": {"name": "binance"},
  "pairlists": [
    {"method": "VolumePairList", "number_assets": ${FETCH_N}, "sort_key": "quoteVolume"}
  ]
}
EOF

echo "=== Resolving top ${FETCH_N} Binance futures pairs by volume ==="

freqtrade test-pairlist \
  --config "$CFG_BASE" \
  --config "$CFG_FUTURES" \
  --config "$VOLUME_CFG" \
  --print-json \
  2>/dev/null | grep '^\[' > "$RAW_JSON_FILE"

if [[ ! -s "$RAW_JSON_FILE" ]]; then
  echo "ERROR: Could not resolve pairlist from Binance. Check internet connection."
  exit 1
fi

# Filter and build the pairlist config
python3 user_data/scripts/_filter_pairlist.py "$RAW_JSON_FILE" "$N_PAIRS" "$PAIRLIST_OUT"

echo ""
echo "=== Downloading candles: timerange=${TIMERANGE}, timeframes=${TIMEFRAMES} ==="
echo ""

freqtrade download-data \
  --config "$CFG_BASE" \
  --config "$CFG_FUTURES" \
  --config "$PAIRLIST_OUT" \
  --timerange "$TIMERANGE" \
  --timeframes $TIMEFRAMES \
  --trading-mode futures \
  --datadir "$DATADIR"

echo ""
echo "=== Download complete ==="
echo "    Data dir : ${DATADIR}/binance/futures/"
echo "    Backtest : --datadir ${DATADIR}/binance"
