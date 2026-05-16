#!/usr/bin/env python3
"""Filter a raw Binance futures pairlist: remove commodities, stocks, garbage tokens.
1000x tokens (e.g. 1000SHIB, 1000BONK, 1000PEPE) are intentionally kept.
Usage: python3 _filter_pairlist.py <raw_json_file> <n_pairs> <output_config_path>
"""
import json
import re
import sys

raw_json_file = sys.argv[1]
n_pairs = int(sys.argv[2])
output_path = sys.argv[3]

with open(raw_json_file) as f:
    raw = json.load(f)

# --- Exclusion lists ---

# Gold, silver, crude oil, nat gas, gold-backed tokens
COMMODITIES = {
    "XAU", "XAG",          # gold, silver (spot)
    "XAUT", "PAXG",        # gold-backed stablecoins
    "CL", "BZ",            # WTI crude, Brent crude
    "NATGAS", "GAS",       # natural gas
    "GOLD", "SILVER", "OIL",
}

# Synthetic stock perpetuals on Binance
STOCKS = {
    "TSLA", "AAPL", "AMZN", "GOOGL", "GOOG", "MSFT", "META",
    "NFLX", "NVDA", "AMD", "INTC", "SNAP", "UBER", "LYFT",
    "COIN", "HOOD", "MSTR", "MARA", "RIOT", "CLSK", "CIFR",
    "SNDK", "BABA", "JD", "NIO", "XPEV", "LI",
}

# Leveraged token suffixes
LEVERAGED_RE = re.compile(r"(UP|DOWN|BULL|BEAR|3L|3S|2L|2S)$", re.IGNORECASE)


def is_crypto(pair: str) -> bool:
    base = pair.split("/")[0]
    # Non-ASCII characters (Chinese text, etc.)
    if not base.isascii():
        return False
    # Commodity or stock
    if base.upper() in COMMODITIES or base.upper() in STOCKS:
        return False
    # Too short — often garbage or stock tickers, but allow known 2-char cryptos
    CRYPTO_SHORT = {"OP", "AR", "AI", "ID"}
    if len(base) < 3 and base.upper() not in CRYPTO_SHORT:
        return False
    # Leveraged tokens
    if LEVERAGED_RE.search(base):
        return False
    return True


filtered = [p for p in raw if is_crypto(p)]
excluded = [p for p in raw if not is_crypto(p)]
top = filtered[:n_pairs]

print(f"Raw from Binance : {len(raw)}")
print(f"Excluded         : {len(excluded)}")
if excluded:
    print(f"  → {', '.join(p.split('/')[0] for p in excluded)}")
print(f"Kept (top {n_pairs})   : {len(top)}")

config = {
    "stake_currency": "USDT",
    "exchange": {
        "name": "binance",
        "pair_whitelist": top,
    },
    "pairlists": [{"method": "StaticPairList"}],
    "entry_pricing": {
        "use_order_book": True,
        "order_book_top": 1,
        "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
    },
    "exit_pricing": {"use_order_book": True, "order_book_top": 1},
}

with open(output_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"\nSaved {len(top)} pairs to: {output_path}")
print("Pairs:", top)
