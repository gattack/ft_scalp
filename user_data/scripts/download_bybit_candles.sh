#!/usr/bin/env bash
# Download candle data for top N Bybit futures pairs by volume.
# Data is stored SEPARATELY from Binance data to avoid overwriting.
#
# Usage: bash user_data/scripts/download_bybit_candles.sh [N_PAIRS] [TIMERANGE]
# Examples:
#   bash user_data/scripts/download_bybit_candles.sh 100 20210101-
#   bash user_data/scripts/download_bybit_candles.sh 100 20250101-
#
# Data lands in:   user_data/data/bybit/futures/
# For backtesting: --datadir user_data/data/bybit

set -euo pipefail

N_PAIRS="${1:-100}"
TIMERANGE="${2:-20210101-}"
DATADIR="user_data/data/bybit"
TIMEFRAMES="5m 15m 1h 4h 1d"

BYBIT_CFG=$(mktemp /tmp/bybit_base_XXXXXX.json)
PAIRLIST_CFG=$(mktemp /tmp/bybit_pairlist_XXXXXX.json)
VOLUME_CFG=$(mktemp /tmp/bybit_volume_XXXXXX.json)
RAW_JSON_FILE=$(mktemp /tmp/bybit_raw_pairs_XXXXXX.json)
AVAILABLE_PAIRLIST="NostalgiaForInfinity/configs/pairlist-backtest-static-bybit-futures-usdt-available.json"
trap 'rm -f "$BYBIT_CFG" "$PAIRLIST_CFG" "$VOLUME_CFG" "$RAW_JSON_FILE"' EXIT

FETCH_N=$(( N_PAIRS * 3 ))

cat > "$BYBIT_CFG" << EOF
{
  "trading_mode": "futures",
  "margin_mode": "isolated",
  "stake_currency": "USDT",
  "exchange": {
    "name": "bybit",
    "key": "",
    "secret": "",
    "pair_whitelist": ["BTC/USDT:USDT"],
    "ccxt_config": {},
    "ccxt_async_config": {}
  },
  "entry_pricing": {
    "use_order_book": true,
    "order_book_top": 1
  },
  "exit_pricing": {
    "use_order_book": true,
    "order_book_top": 1
  },
  "pairlists": [{"method": "StaticPairList"}]
}
EOF

cat > "$VOLUME_CFG" << EOF
{
  "exchange": {"name": "bybit"},
  "pairlists": [
    {"method": "VolumePairList", "number_assets": ${FETCH_N}, "sort_key": "quoteVolume"}
  ]
}
EOF

echo "=== Resolving top ${FETCH_N} Bybit futures pairs by volume ==="

freqtrade test-pairlist \
  --config "$BYBIT_CFG" \
  --config "$VOLUME_CFG" \
  --print-json \
  2>/dev/null | grep '^\[' > "$RAW_JSON_FILE"

if [[ ! -s "$RAW_JSON_FILE" ]]; then
  echo "ERROR: Could not resolve pairlist from Bybit. Check internet connection."
  exit 1
fi

python3 user_data/scripts/_filter_pairlist.py "$RAW_JSON_FILE" "$N_PAIRS" "$PAIRLIST_CFG"

# Fix exchange name — _filter_pairlist.py hardcodes "binance"
python3 -c "
import json
with open('$PAIRLIST_CFG') as f:
    cfg = json.load(f)
cfg['exchange']['name'] = 'bybit'
with open('$PAIRLIST_CFG', 'w') as f:
    json.dump(cfg, f, indent=2)
"

PAIR_COUNT=$(python3 -c "import json; print(len(json.load(open('$PAIRLIST_CFG'))['exchange']['pair_whitelist']))")
echo "Resolved ${PAIR_COUNT} Bybit futures pairs"

# Save the resolved pairlist permanently for use by backtest scripts
cp "$PAIRLIST_CFG" "$AVAILABLE_PAIRLIST"
echo "Pairlist saved to: $AVAILABLE_PAIRLIST"

echo ""
echo "=== Downloading Bybit candles: timerange=${TIMERANGE}, timeframes=${TIMEFRAMES} ==="
echo ""

freqtrade download-data \
  --config "$BYBIT_CFG" \
  --config "$PAIRLIST_CFG" \
  --timerange "$TIMERANGE" \
  --timeframes $TIMEFRAMES \
  --trading-mode futures \
  --datadir "$DATADIR"

echo ""
echo "=== Download complete ==="
echo "    Data dir : ${DATADIR}/futures/"
echo "    Pairlist : $AVAILABLE_PAIRLIST"
echo "    Backtest : --datadir ${DATADIR}"
echo "    Pairs    : ${PAIR_COUNT}"
