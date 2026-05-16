# AGENTS.md

Compact instructions for OpenCode agents working in this repo. Full details are in `CLAUDE.md`.

## Critical rules

- **Always use monthly backtest scripts** (`run_binance100_backtest.sh`, `run_monthly_backtests.sh`, etc.) for multi-month backtests. Never run a single backtest spanning many months — monthly scripts handle per-month pair filtering (skipping pairs without 20-day warmup data), produce consistent filenames, and skip existing months automatically.

## Quick commands

```bash
# Lint (config: NostalgiaForInfinity/pyproject.toml)
black --line-length 119 user_data/strategies/
ruff check user_data/strategies/

# Unit tests
cd NostalgiaForInfinity && pytest tests/unit/ -v

# Download Binance candle data (top 150 pairs)
bash user_data/scripts/download_candles.sh 150 20250101-

# Download Bybit candle data (top 100 pairs, separate dir — won't overwrite Binance)
bash user_data/scripts/download_bybit_candles.sh 100 20210101-

# Run 12 monthly backtests (X7 default, pass strategy name as arg)
bash user_data/scripts/run_monthly_backtests.sh [NostalgiaForInfinityX7]

# Run Apr 2024–Mar 2025 backtests (prior year, X7 then CombinedFast)
bash user_data/scripts/run_2024_backtests.sh [STRATEGY]

# Multi-year backtests
bash user_data/scripts/run_2year_backtest.sh [NostalgiaScalpPro]     # Apr24–Apr26
bash user_data/scripts/run_5year_backtest.sh [NostalgiaScalpPro]     # Apr21–Apr26
bash user_data/scripts/run_bybit_5year_backtest.sh [NostalgiaScalpPro] # Bybit 5yr
bash user_data/scripts/run_binance100_backtest.sh [NostalgiaScalpPro] # Binance top-100
bash user_data/scripts/run_150pairs_backtest.sh                       # NostalgiaScalpPro150

# Summarize monthly results
python3 user_data/scripts/summarize_monthly.py [--strategy X7] [--results-dir DIR]

# Per-tag performance analysis
python3 user_data/scripts/analyze_tags.py --strategy NostalgiaScalpPro \
  [--min-trades 5] [--min-winrate 95] [--results-dir DIR]

# Single Binance backtest
freqtrade backtesting \
  --config NostalgiaForInfinity/configs/exampleconfig.json \
  --config NostalgiaForInfinity/configs/trading_mode-futures.json \
  --config NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json \
  --strategy NostalgiaForInfinityX7 \
  --strategy-path user_data/strategies \
  --timerange 20250401-20250501 \
  --datadir NostalgiaForInfinity/user_data/data \
  --export trades \
  --backtest-directory user_data/backtest_results/monthly \
  --notes "label_for_this_run"

# Show backtest results
freqtrade backtesting-show --backtest-filename user_data/backtest_results/monthly/backtest_NostalgiaForInfinityX7_202504.zip
```

## Critical constraints

- **Timeframe is always 5m** — changing it breaks all indicator calculations
- **Never edit files in `NostalgiaForInfinity/`** — upstream repo, edits will be overwritten. All local work goes in `user_data/`
- Backtest results are `.zip` (freqtrade 2026.x), not `.json` — use `--backtest-directory`, not `--export-filename`
- Pairs without leverage tiers (KAT, CHIP, BSB, OPG, BASED, GENIUS, ROBO) crash freqtrade — keep them out of pairlists
- `startup_candle_count = 800` on 5m; pairs need 4h data starting ≥20 days before backtest start or `.diff()` crashes with `TypeError: NoneType - NoneType`
- Use `20250101-` (not `20250401-`) when backtesting from Apr 2025 to satisfy the 20-day warmup

## Data directories

| Exchange | `--datadir` | Candle files | Notes |
|----------|-------------|--------------|-------|
| Binance | `NostalgiaForInfinity/user_data/data` | `…/futures/*.feather` | Primary, used by all existing backtests |
| Bybit | `user_data/data/bybit` | `…/futures/*.feather` | Separate — never overwrites Binance |

- `data/binance/futures/` is legacy upstream data — not used

## Backtest results layout

```
user_data/backtest_results/
├── monthly/      # Binance results (run_monthly_backtests.sh, run_2024_backtests.sh, etc.)
├── bybit/        # Bybit results (run_bybit_5year_backtest.sh)
└── binance100/   # Binance top-100 results (run_binance100_backtest.sh)
```
All use filename convention: `backtest_{STRATEGY}_{YYYYMM}.zip`. Scripts skip existing zips — safe to re-run after interruption.

## Strategy files (`user_data/strategies/`)

| File | Purpose |
|---|---|
| `NostalgiaForInfinityX7.py` | Local copy of upstream latest — benchmarking |
| `NostalgiaForInfinityX6.py` | Local copy of upstream stable |
| `NostalgiaCombinedFast.py` | X6+X7 wrapper with tag filtering + SQLite logging |
| `NostalgiaCombinedFastAllTags.py` | Same, no tag whitelist |
| `NostalgiaScalpPro.py` | 12-condition no-DCA scalp strategy; inherits X7 |
| `NostalgiaScalpProOptimized.py` | **Preferred for scalp backtesting** — same logic, ~40% faster indicators |
| `NostalgiaScalpPro150.py` | Thin subclass for 150-pair runs (distinct filenames) |
| `NostalgiaForInfinityX5.py` | Downloaded from upstream — older version for comparison backtests |
| `NostalgiaScalpPro_v5_backup.py` | Archived earlier version — do not use |
| `NostalgiaScalpProX6X7.py` | Reference copy of X6X7 wrapper (original, non-optimized indicators) |
| `NostalgiaScalpProX6X7Opt.py` | Optimized X6X7 wrapper (5m indicators: 56→36 cols, ~39% faster); has `version()` method; parent class for X6X7Exp |
| `NostalgiaScalpProX6X7Exp.py` | **Current live bot strategy** — X6X7Opt + tag 705a (MFI Volume Capitulation) with progressive loss cuts and per-pair cooldown. v26.04.30.exp9. See §Experimental 705a below. |
| `NostalgiaScalpProX5X6X7.py` | Candidate live upgrade — adds X5 tag 41 on top of X6X7Opt |
| `NostalgiaScalpProOptimizedOrig.py` | Archive — pre-optimization snapshot; do not use |
| `NostalgiaScalpPro_v5_backup.py` | Archive — v5 snapshot; do not use |

**When to use which:** `NostalgiaScalpProOptimized` for new backtests (90-pair pairlist); `NostalgiaScalpPro150` only when testing 150 pairs; `NostalgiaForInfinityX7` for standard benchmarking; `NostalgiaForInfinityX5` for older-version comparison; `NostalgiaScalpProX5X6X7` as candidate live upgrade; `NostalgiaCombinedFast` for feature logging to SQLite (`user_data/models/nfi_signal_meta/signals.sqlite`); `NostalgiaScalpProX6X7Exp` is the current live bot on all three VPS instances.

## Config layering (order matters)

Configs merge sequentially. Always use all three:
1. `configs/exampleconfig.json` — base (6 max trades, dry_run)
2. `configs/trading_mode-futures.json` — futures overrides
3. `configs/pairlist-backtest-static-binance-futures-usdt-available.json` — pairs with local data

Blacklists are separate: `configs/blacklist-binance.json`.

## Per-month pair filtering

`run_monthly_backtests.sh` and similar scripts filter pairs per month — pairs without 20-day pre-start 4h history are skipped for that month only. This prevents `TypeError` crashes from insufficient warmup data. Don't bypass it.

## Pairlist files

- `pairlist-backtest-static-binance-futures-usdt.json` — upstream full list (343 pairs, most without local data)
- `pairlist-backtest-static-binance-futures-usdt-available.json` — **auto-generated** by `download_candles.sh`, only pairs with local feather files
- `pairlist-backtest-static-binance-futures-usdt-top100.json` — first 100 of available list; used by `run_binance100_backtest.sh` for fair Bybit comparison
- `pairlist-backtest-static-bybit-futures-usdt-available.json` — **auto-generated** by `download_bybit_candles.sh`

## VPS live bots

**Four Tencent servers.** All run `NostalgiaScalpProX6X7Exp`. Deploy hits all four. Use `restart` for strategy-only deploys; `up -d --force-recreate` when docker-compose.yml command changes. (Alibaba `109.199.110.135` was retired 2026-05-15.)

| IP | Exchange | Container | Role |
|----|----------|-----------|------|
| `43.156.128.160` | Binance | `freqtrade_scalp_exp` | scalp dedicated |
| `43.128.72.96` | Binance | `freqtrade_scalp_copytrade` | Binance copytrade lead |
| `150.109.17.13` | Bybit | `freqtrade_scalp_bybit` | scalp dedicated |
| `129.226.90.189` | Bybit | `freqtrade_scalp_bybit_ct` | Bybit copytrade lead |

### Tencent — Binance scalp (43.156.128.160)

SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.156.128.160`

Container `freqtrade_scalp_exp`, dir `/opt/freqtrade_scalp/`, port 8092, Binance Futures, 2 vCPU / 2 GB RAM. API `http://43.156.128.160:8092` (freqtrader/<DASHBOARD_PASS>), Telegram token `8739971971:…` chat `1212757518`.

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@43.156.128.160:/opt/freqtrade_scalp/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.156.128.160 "cd /opt/freqtrade_scalp && sudo docker compose restart"
```

### Tencent — Binance copytrade (43.128.72.96)

SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.128.72.96`. Container `freqtrade_scalp_copytrade`, dir `/opt/freqtrade_scalp/`, Binance Futures, dedicated Binance copytrade lead account, same deploy pattern as `43.156.128.160` (swap the IP). bot_name `NFI_ScalpPro_CopyTrade`, distinct jwt_secret_key `<JWT_SECRET>`.

### Tencent — Bybit scalp (150.109.17.13)

SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@150.109.17.13`

Container `freqtrade_scalp_bybit`, dir `/opt/freqtrade_scalp_bybit/`, port 8092, Bybit Futures, 2 vCPU / 2 GB RAM. API `http://150.109.17.13:8092` (freqtrader/<DASHBOARD_PASS>), Telegram token `8799144353:…` chat `1212757518`.

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@150.109.17.13:/opt/freqtrade_scalp_bybit/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@150.109.17.13 "cd /opt/freqtrade_scalp_bybit && sudo docker compose restart"
```

### Tencent — Bybit copytrade (129.226.90.189)

SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@129.226.90.189`. Container `freqtrade_scalp_bybit_ct`, dir `/opt/freqtrade_scalp_bybit/`, Bybit Futures, dedicated Bybit copytrade lead account, same deploy pattern as `150.109.17.13` (swap the IP). bot_name `NFI_ScalpPro_Bybit_CopyTrade`. Bybit API key must have `129.226.90.189` whitelisted (failure: `retCode 10010 "Unmatched IP"`).

### Live VPS pairlist & blacklist

All four Tencent VPS use a **dynamic** `VolumePairList`. Static `pair_whitelist` in `config.json` is just `BTC/USDT:USDT` — pairs are picked at runtime by exchange volume.

Pipeline: `VolumePairList`(top 90) → `FullTradesFilter` → `AgeFilter`(≥60d) → `PriceFilter`(≥0.3%) → `SpreadFilter`(≤0.5%) → `RangeStabilityFilter`(3d RoC 0.03–2.0) → `VolumePairList`(final top 75). Refresh ~63 min.

**Live `pair_blacklist` regex** (rejects commodities/stocks/leveraged tokens the volume sort would otherwise admit):
- Commodities: `(XAU|XAUT|XAG|OIL|GAS|PAXG)/.*`
- Stocks: `(TSLA|AAPL|MSTR|GOOGL|AMZN|NVDA|COIN|INTC|CRCL)/.*`
- Leveraged tokens: `.*(_PREMIUM|BEAR|BULL|HALF|HEDGE|UP|DOWN|[1235][SL])/.*`
- Fiat / stablecoin quote regexes (see CLAUDE.md for full list)
- Explicit no-leverage-tier: `KAT`, `CHIP`, `BSB`, `OPG`, `BASED`, `ROBO`, `GENIUS` (Tencent Binance also: `AIOT`, `BLESS`)

**Verify live whitelist** (over SSH tunnel): `curl -s -u freqtrader:<DASHBOARD_PASS> http://127.0.0.1:8092/api/v1/whitelist`. When new exchange products launch (tokenized stocks, gold spot etc.), they can enter the top-75 by volume before the regex catches them — extend the regex if found. Confirmed incident 2026-05-06: XAU, INTC, CRCL slipped through on Tencent Binance; regex extended.

## Architecture in 30 seconds

NFI strategies load 5m candles + informative timeframes (15m, 1h, 4h, 1d). Entries are tagged (`long_1`, `short_501`, etc.) mapping to numbered conditions. Only conditions enabled in `buy_params`/`sell_params` are active. Position management uses `adjust_trade_position()` (grinding/rebuy) and `custom_exit()` (mode-specific exits). NostalgiaCombinedFast inherits from `IStrategy`, delegates to X6/X7 child instances, logs features to SQLite at `user_data/models/nfi_signal_meta/signals.sqlite`.

## Backtest results (X5, Binance top-100)

### NostalgiaForInfinityX5 — 2-year completed (Apr 2024–Apr 2026, 24 months)

Run completed: April 2026. Strategy: NostalgiaForInfinityX5, Binance Futures top-100 pairs, 5m timeframe.

| Month | Trades | Win% | Profit% | Max DD% |
|-------|--------|------|---------|---------|
| 202404 | 27 | 96.3% | +8.07% | 10.19% |
| 202405 | 2 | 100% | +1.73% | 0.00% |
| 202406 | 29 | 100% | +53.63% | 0.00% |
| 202407 | 6 | 100% | +7.76% | 0.00% |
| 202408 | 14 | 92.9% | +5.18% | 7.31% |
| 202409 | 3 | 100% | +2.56% | 0.00% |
| 202410 | 17 | 100% | +15.31% | 0.00% |
| 202411 | 15 | 100% | +17.53% | 0.00% |
| 202412 | 43 | 97.7% | +37.40% | 11.47% |
| 202501 | 14 | 100% | +18.30% | 0.00% |
| 202502 | 34 | 94.1% | +24.41% | 6.94% |
| 202503 | 24 | 95.8% | +11.09% | 10.24% |
| 202504 | 20 | 100% | +29.17% | 0.00% |
| 202505 | 14 | 92.9% | +0.59% | 11.12% |
| 202506 | 12 | 91.7% | -0.55% | 8.54% |
| 202507 | 18 | 94.4% | +3.74% | 10.26% |
| 202508 | 19 | 94.7% | +9.12% | 6.16% |
| 202509 | 23 | 87.0% | -9.95% | 18.43% |
| 202510 | 47 | 95.7% | +94.12% | 16.54% |
| 202511 | 44 | 86.4% | +10.07% | 22.98% |
| 202512 | 43 | 90.7% | +19.87% | 12.17% |
| 202601 | 59 | 93.2% | +27.59% | 23.92% |
| 202602 | 58 | 94.8% | +52.79% | 14.69% |
| 202603 | 97 | 94.8% | -10.32% | 58.59% |

**Aggregate (24 months):** 682 trades, 645W/37L, **94.6% win rate**, compounded **+3,426% ($10k → $352k)**, worst DD 58.59% (Mar 2026). 3 losing months.

### NostalgiaForInfinityX5 — 5-year COMPLETE (May 2021–Apr 2026, 60 months)

**Status: COMPLETE** (60 zips in `user_data/backtest_results/binance100/`). Aggregate: 1,245 trades, 1,175W/70L, **94.4% WR**, compounded **+149,656% ($10k → $14.97M)**, worst DD 58.59% (Mar 2026).

```bash
python3 user_data/scripts/summarize_monthly.py --strategy NostalgiaForInfinityX5 --results-dir user_data/backtest_results/binance100
```

## Experimental 705a (NostalgiaScalpProX6X7Exp)

### What it is

X6X7Opt base + one new entry signal (tag 705a: MFI Volume Capitulation) with active loss management. Currently deployed on all three live VPS instances.

### Tag 705a entry conditions

Uses only indicator columns already computed by `NostalgiaScalpProOptimized` (no new indicator calculations):

```
protections_ok AND
RSI_3 < 40            AND   # 5m RSI(3) deeply oversold
MFI_14_1h < 20        AND   # 1h MFI(14) extreme capitulation volume
RSI_3_15m < 10        AND   # 15m RSI(3) near-zero
close < EMA_12 * 0.95 AND   # price 5%+ below 4h EMA(12)
AROONU_14 < 25        AND   # aroon up near zero (strong downtrend)
STOCHRSIk_14_14_3_3_15m < 20 AND  # 15m StochRSI oversold
WILLR_14 < -80        AND   # 5m Williams %R deeply oversold (705a filter)
close > open * 1.01         # green candle bounce confirmation (exp9)
```

The `WILLR_14 < -80` filter removed 3 of 4 historical catastrophic losses (CRV/DYDX/ARB Apr 2024 force-exits). The `close > open * 1.01` filter (exp9) removed 9 of 10 remaining red-body losses.

### Risk management

**For exp_ trades (tag 705a):**
1. **Entry filters**: `WILLR_14 < -80` prevents mid-range oscillation entries; `close > open * 1.01` (exp9) requires green candle bounce confirmation
2. **Progressive loss cuts** via `custom_exit()` (evaluated every 5m candle):
   - 10 min / profit < -5% → `exp_cut_5pct`
   - 15 min / profit < -3% → `exp_cut_3pct`
   - 30 min / profit < -2% → `exp_cut_2pct`
   - 60 min / profit < -1% → `exp_cut_1pct`
   - 120 min / any loss → `exp_timeout_exit`
3. **Per-pair 4-hour cooldown**: after any exp_ loss exit, block re-entry on that pair for 4 hours. Prevents "death spiral" re-entries during cascading crashes (e.g., PIPPIN entered 5× in 1.5h during Mar 2026 crash)

**For non-exp (x6_/x7_) trades — class-level `stoploss = -0.10` DOES NOT FIRE:**
`NostalgiaForInfinityX7.confirm_trade_exit` (line 11598) denies `stop_loss` / `trailing_stop_loss` in both live AND backtest — only true liquidation crossings are allowed through. The configured stoploss is therefore dead. Backtest "max DD" numbers are optimistic because end-of-period `force_exit` masks tail risk.

Compensating gentle backstop ladder in `NostalgiaScalpProX6X7Exp.custom_exit` (after `super().custom_exit()` returns None):
   - 60 min / profit ≤ -15% → `backstop_1h_15pct`
   - 240 min / profit ≤ -10% → `backstop_4h_10pct`
   - 720 min / profit ≤ -5% → `backstop_12h_5pct`
   - 2880 min / profit < 0 → `backstop_48h_timeout`

`force_exit` is the only `exit_reason` X7 lets through unconditionally — use `POST /api/v1/forceexit` for manual intervention.

### Critical implementation details

- **Co-fire detection**: `_PFX_EXP in tag` (not `startswith()`) — tag 705a can co-fire with X7 tags (e.g., `x7_61 exp_705a`). The loss management must detect exp_ anywhere in the tag string.
- **`_resolve()` override**: extracts the exp_ portion from co-fired tags for correct X7 exit routing.
- **`custom_exit()` ordering**: exp loss checks run BEFORE `super().custom_exit()`; non-exp backstop ladder runs AFTER (so X7's own exits take priority).
- **Cooldown state**: `self._exp_last_loss` dict tracks per-pair last loss datetime. Checked in `confirm_trade_entry()` to block exp_ re-entries. State persists within a backtest run but not across restarts. Non-exp trades have no cooldown.

### Backtest results — 28 months (Jan 2024–Apr 2026, Binance top-100)

Clean results in `user_data/backtest_results/binance100/`.

| Month | Trades | Win% | Profit% | Max DD% |
|-------|--------|------|---------|---------|
| 202401 | 9 | 100% | +20.84% | 0.00% |
| 202402 | 4 | 100% | +4.54% | 0.00% |
| 202403 | 12 | 100% | +12.80% | 0.00% |
| 202404 | 13 | 100% | +8.26% | 0.00% |
| 202405 | 0 | — | 0.00% | 0.00% |
| 202406 | 10 | 100% | +14.11% | 0.00% |
| 202407 | 1 | 100% | +1.13% | 0.00% |
| 202408 | 12 | 100% | +8.20% | 0.00% |
| 202409 | 0 | — | 0.00% | 0.00% |
| 202410 | 5 | 100% | +5.10% | 0.00% |
| 202411 | 4 | 100% | +6.69% | 0.00% |
| 202412 | 29 | 100% | +47.81% | 0.00% |
| 202501 | 13 | 100% | +16.39% | 0.00% |
| 202502 | 28 | 100% | +32.76% | 0.00% |
| 202503 | 11 | 100% | +12.70% | 0.00% |
| 202504 | 2 | 100% | +1.82% | 0.00% |
| 202505 | 3 | 100% | +3.47% | 0.00% |
| 202506 | 4 | 100% | +6.85% | 0.00% |
| 202507 | 4 | 100% | +2.79% | 0.00% |
| 202508 | 6 | 100% | +4.47% | 0.00% |
| 202509 | 4 | 100% | +12.03% | 0.00% |
| 202510 | 21 | 100% | +87.06% | 0.00% |
| 202511 | 11 | 100% | +11.04% | 0.00% |
| 202512 | 15 | 100% | +12.62% | 0.00% |
| 202601 | 8 | 100% | +9.44% | 0.00% |
| 202602 | 23 | 100% | +35.23% | 0.00% |
| 202603 | 49 | 98% | +101.60% | 7.64% |
| 202604 | 30 | 97% | +55.96% | 7.64% |

**Aggregate (26 active months):** 331 trades, 329W/2L, **99.4% win rate**, compounded **+8,095% ($10k → $820k)**, worst DD 7.64%. Zero losing months.

### Per-tag breakdown (28 months)

| Tag | Trades | WR% | Avg Profit | Worst Loss |
|-----|--------|-----|------------|------------|
| exp_705a | 4 | 100% | +29.0% | 0% |
| x6_62 | 48 | 100% | +7.8% | 0% |
| x6_143 | 58 | 100% | +6.9% | 0% |
| x7_4 | 22 | 100% | +8.9% | 0% |
| x7_41 | 21 | 100% | +6.7% | 0% |
| x7_42 | 31 | 100% | +6.5% | 0% |
| x7_44 | 12 | 100% | +14.2% | 0% |
| x7_45 | 7 | 100% | +24.0% | 0% |
| x7_46 | 8 | 100% | +4.3% | 0% |
| x7_5 | 7 | 100% | +6.9% | 0% |
| x7_61 | 36 | 100% | +14.2% | 0% |
| x7_102 | 17 | 88.2% | -1.7% | -52.6% |
| x7_104 | 7 | 100% | +7.1% | 0% |
| x7_161 | 10 | 100% | +6.1% | 0% |
| x7_162 | 7 | 100% | +6.2% | 0% |
| x7_163 | 25 | 100% | +5.9% | 0% |

### Comparison: X6X7Opt baseline vs X6X7Exp (exp9)

| Metric | X6X7Opt | X6X7Exp (exp9) | Change |
|--------|---------|----------------|--------|
| Total trades | ~264 | 331 | +67 |
| Win rate | ~100% | 99.4% | -0.6% |
| Compounded (28mo) | ~2,500% | 8,095% | +5,595% |
| Worst drawdown | ~14% | 7.64% | better |
| Losing months | 0 | 0 | same |

The exp9 green candle filter (`close > open * 1.01`) reduced 705a from 29 trades (72.4% WR, 8 losses) down to 4 trades (100% WR, 0 losses). The x7_102 tag has 2 losses (both -52.6%, BULLA force-exit) — the only losses in the entire 28-month run.

### Files required on VPS (if deployed)

Same as X6X7Opt plus the Exp file:
- `NostalgiaScalpProX6X7Exp.py`
- `NostalgiaScalpProX6X7Opt.py`
- `NostalgiaScalpProOptimized.py`
- `NostalgiaForInfinityX6.py`

### How to backtest

```bash
bash user_data/scripts/run_binance100_backtest.sh NostalgiaScalpProX6X7Exp
```

Or single month:
```bash
freqtrade backtesting \
  --config NostalgiaForInfinity/configs/exampleconfig.json \
  --config NostalgiaForInfinity/configs/trading_mode-futures.json \
  --config NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-top100.json \
  --strategy NostalgiaScalpProX6X7Exp \
  --strategy-path user_data/strategies \
  --timerange 20260301-20260401 \
  --datadir NostalgiaForInfinity/user_data/data \
  --export trades \
  --backtest-directory user_data/backtest_results/binance100 \
  --notes "exp9_202603"
```
