# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a **NostalgiaForInfinity (NFI)** Freqtrade strategy project. Upstream strategy files live in `NostalgiaForInfinity/` (do not edit — auto-updated by the sidecar). All local work goes in `user_data/`.

`AGENTS.md` in the repo root is a parallel quick-reference optimized for OpenCode agents — it contains the same critical rules in a condensed format.

Archived/backup strategy files (do not use or edit): `NostalgiaScalpProOptimizedOrig.py` (pre-optimization snapshot), `NostalgiaScalpPro_v5_backup.py` (v5 archive).

- **Timeframe**: Always 5m (mandatory — changing it breaks all indicator calculations)
- **Exchange**: Binance Futures (USDT-margined); Bybit Futures also supported
- **Mode**: Futures, long-only (scalp strategies); X7 supports short

## Data directory layout (important)

Freqtrade separates `--datadir` semantics between commands:

| Command | `--datadir` value | Files land at |
|---|---|---|
| `download-data` (Binance) | `NostalgiaForInfinity/user_data/data` | `…/futures/*.feather` |
| `backtesting` (Binance) | `NostalgiaForInfinity/user_data/data` | freqtrade looks in `…/futures/` |
| `download-data` (Bybit) | `user_data/data/bybit` | `…/futures/*.feather` |
| `backtesting` (Bybit) | `user_data/data/bybit` | freqtrade looks in `…/futures/` |

Binance and Bybit data never overwrite each other. `NostalgiaForInfinity/user_data/data/binance/futures/` is legacy upstream data — not used.

## Common Commands

### Lint / test
```bash
black --line-length 119 user_data/strategies/
ruff check user_data/strategies/
cd NostalgiaForInfinity && pytest tests/unit/ -v
```
Linting config is in `NostalgiaForInfinity/pyproject.toml`.

### Download candle data
```bash
# Top 150 Binance pairs (recommended; use 20250101- when backtesting from Apr 2025)
bash user_data/scripts/download_candles.sh 150 20250101-

# Top 100 Bybit pairs (separate dir, won't overwrite Binance)
bash user_data/scripts/download_bybit_candles.sh 100 20210101-

# Manual / specific pairs
freqtrade download-data \
  --config NostalgiaForInfinity/configs/exampleconfig.json \
  --config NostalgiaForInfinity/configs/trading_mode-futures.json \
  --config NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json \
  --timerange 20210101- \
  --timeframes 5m 15m 1h 4h 1d \
  --trading-mode futures \
  --datadir NostalgiaForInfinity/user_data/data
```
`download_candles.sh` calls `_filter_pairlist.py` which excludes commodities (XAU/XAG/OIL/GAS/XAUT/PAXG), stocks (TSLA/AAPL/MSTR etc.), and leveraged tokens (*BULL/*BEAR/*UP/*DOWN). **1000x tokens are intentionally kept.**

### Run backtests

**Always use monthly scripts for multi-month runs** — they handle per-month pair filtering (pairs without 20-day warmup data are skipped), produce consistent filenames, and skip existing months automatically.

```bash
# 12-month Binance backtest (Apr 2025–Apr 2026); default strategy X7
bash user_data/scripts/run_monthly_backtests.sh [NostalgiaForInfinityX7]

# 24-month Binance (Apr 2024–Apr 2026)
bash user_data/scripts/run_2year_backtest.sh [NostalgiaScalpPro]

# 60-month Binance (Apr 2021–Apr 2026)
bash user_data/scripts/run_5year_backtest.sh [NostalgiaScalpPro]

# 60-month Bybit
bash user_data/scripts/run_bybit_5year_backtest.sh [NostalgiaScalpPro]

# 27-month Binance top-100 (Jan 2024–Apr 2026; apples-to-apples vs Bybit top-100)
bash user_data/scripts/run_binance100_backtest.sh [NostalgiaScalpPro]

# 150-pair variant
bash user_data/scripts/run_150pairs_backtest.sh

# 12-month Binance (Apr 2024–Apr 2025; useful for historical year comparison)
bash user_data/scripts/run_2024_backtests.sh [NostalgiaScalpPro]
```

### Single backtest
```bash
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

# Show results
freqtrade backtesting-show --backtest-filename user_data/backtest_results/monthly/backtest_NostalgiaForInfinityX7_202504.zip
```

### Analyze results
```bash
# Summary table across all monthly zips
python3 user_data/scripts/summarize_monthly.py [--strategy NostalgiaScalpPro] [--results-dir DIR]

# Per-entry-tag stats (use to decide which conditions to disable)
python3 user_data/scripts/analyze_tags.py --strategy NostalgiaScalpPro \
  [--min-trades 5] [--min-winrate 95] [--max-duration-h 4] [--max-avg-loss -15] \
  [--results-dir user_data/backtest_results/bybit]
```

## Architecture

### Strategy files (`user_data/strategies/`)

| File | Purpose |
|---|---|
| `NostalgiaForInfinityX7.py` | Local copy of upstream latest — benchmarking |
| `NostalgiaForInfinityX6.py` | Local copy of upstream stable |
| `NostalgiaForInfinityX5.py` | Downloaded from upstream — older version for comparison backtests |
| `NostalgiaCombinedFast.py` | X6+X7 wrapper with tag filtering + SQLite logging to `user_data/models/nfi_signal_meta/signals.sqlite` |
| `NostalgiaCombinedFastAllTags.py` | Same as CombinedFast, no fast-mode tag whitelist |
| `NostalgiaScalpPro.py` | 16-condition no-DCA scalp strategy; inherits X7 |
| `NostalgiaScalpProOptimized.py` | **Preferred for scalp backtesting** — same signals as ScalpPro, ~40% fewer indicator columns |
| `NostalgiaScalpPro150.py` | Thin subclass of Optimized for 150-pair runs (distinct filenames) |
| `NostalgiaScalpProX6X7.py` | Reference copy of X6X7 wrapper (original, non-optimized indicators); do not use for new work |
| `NostalgiaScalpProX6X7Opt.py` | **Current live bot** (deployed 2026-05-17) — multi-child X6+X7 wrapper, ~39% faster indicators, no synthetic backstops (relies on X6/X7 native exits) |
| `NostalgiaScalpProX6X7Exp.py` | **Previous live bot** (2026-05-16 → 2026-05-17) — X6X7Opt + tag 705a + progressive loss cuts + per-pair cooldown + backstop ladder. Kept for rollback / reference |
| `NostalgiaScalpProX5X6X7.py` | Candidate upgrade — adds X5 tag 41 on top of X6X7Opt |
| `NostalgiaScalpProOptimizedOrig.py` | Archive — pre-optimization snapshot; do not use |
| `NostalgiaScalpPro_v5_backup.py` | Archive — v5 snapshot; do not use |

### Strategy inheritance chain

```
NostalgiaForInfinityX5   (upstream, ~55k lines)
NostalgiaForInfinityX6   (upstream stable, ~65k lines)
NostalgiaForInfinityX7   (upstream latest, ~77k lines)
  └── NostalgiaScalpPro            (16 X7 conditions, no DCA)
        └── NostalgiaScalpProOptimized   (~40% fewer indicator columns; identical signals)
              └── NostalgiaScalpPro150   (class rename only, for distinct filenames)

IStrategy (direct)
  └── NostalgiaScalpProX6X7Opt     ← CURRENT LIVE BOT (since 2026-05-17); multi-child X6 tags 62/143 + X7 12 ScalpPro tags
        └── NostalgiaScalpProX6X7Exp   (previously live 2026-05-16 → 2026-05-17; adds tag 705a + loss cuts + cooldown; kept for rollback)
  └── NostalgiaScalpProX6X7        (reference copy of X6X7Opt, non-optimized; do not use for new work)
  └── NostalgiaScalpProX5X6X7      (candidate upgrade: adds X5 tag 41 on top of X6X7)
  └── NostalgiaCombinedFast        (X6+X7 wrapper, fast-mode tags only, logs features to SQLite)
        └── NostalgiaCombinedFastAllTags   (same but without fast-mode whitelist)
```

### Which strategy to use

| Goal | Strategy |
|------|----------|
| **Live bot (current)** | `NostalgiaScalpProX6X7Opt` |
| Scalp backtesting (90-pair) | `NostalgiaScalpProOptimized` |
| Scalp backtesting (150-pair) | `NostalgiaScalpPro150` |
| Full X7 benchmarking (all conditions + DCA) | `NostalgiaForInfinityX7` |
| Historical comparison (pre-X6) | `NostalgiaForInfinityX5` |
| Candidate live upgrade | `NostalgiaScalpProX5X6X7` |
| Feature logging for ML | `NostalgiaCombinedFast` |
| Feature logging (all tags, no fast-mode filter) | `NostalgiaCombinedFastAllTags` |

### Multi-child strategy architecture (X6X7Opt / X6X7Exp / X5X6X7)

These strategies instantiate multiple NFI child instances and merge their signals:

- `populate_indicators` runs `NostalgiaScalpProOptimized` only (~40% fewer columns vs full X7; superset of what X5/X6 tags 41/62/143 need)
- `populate_entry_trend` runs both/all children, filters each to its allowed tag set, then prefixes tags: `x5_41`, `x6_62`, `x6_143`, `x7_4`, `x7_45`, etc.
- **Priority**: X6 > X5 > X7 (X6 entries overwrite lower-priority signals on the same candle)
- `custom_exit` strips the prefix and delegates to the originating child — X6 entries get X6 exits, X7 entries get X7 exits. No mixing.
- `_bool_signal()` / `_tag_allowed()` are utility functions defined locally in each multi-child file to handle mixed-type signal columns and multi-token tag strings

**Critical**: Both X6 and X5 children must have `short_entry_signal_params = {}` — their default short conditions reference `RSI_3_change_pct_1h` which `NostalgiaScalpProOptimized` drops. All scalp strategies are long-only.

### NostalgiaScalpProX6X7Exp (PREVIOUS live bot 2026-05-16 → 2026-05-17) — tag 705a

Last deployed version: **`26.05.16.exp11`** (deployed to all 4 Tencent VPS 2026-05-16, replaced 2026-05-17 by X6X7Opt). Reason for rollback to Opt: a 6-month Dec 2025 – May 16 2026 backtest (run 2026-05-17) showed Opt at +199.19% compounded / 98.7% WR / 1.19% worst-DD vs Exp at +117.69% / 82.5% WR / 7.50% worst-DD — the backstop ladder fired 14 times on losers that the X7 child would have exited at smaller losses or held to recovery. The exp_705a tag itself never fired in this window (WILLR + green-candle filters), so it contributed zero upside. Switch back to Exp if a tail-risk regime returns and the backstops start paying for themselves; the 28-month historical aggregate (+8,095% on Exp vs ~2,500% on Opt) was driven by Apr 2024 / Mar 2026 stress events that aren't present in the current window.

Tag 705a (MFI Volume Capitulation) adds a mean-reversion scalp on top of X6X7Opt. Entry conditions use only columns already computed by `NostalgiaScalpProOptimized`:

```
RSI_3 < 40  AND  MFI_14_1h < 20  AND  RSI_3_15m < 10  AND
close < EMA_12 * 0.95  AND  AROONU_14 < 25  AND
STOCHRSIk_14_14_3_3_15m < 20  AND  WILLR_14 < -80  AND
close > open * 1.01   # green candle bounce (exp9 filter)
```

Filter rationale: `WILLR_14 < -80` removed 3 of 4 historical catastrophic losses (CRV/DYDX/ARB Apr 2024 force-exits). `close > open * 1.01` (exp9) removed 9 of 10 remaining red-body losses.

Risk management for **exp_** trades (tag 705a):
1. **Progressive loss cuts** via `custom_exit` (every 5m): `10min/-5%`, `15min/-3%`, `30min/-2%`, `60min/-1%`, `120min/any loss`
2. **Per-pair 4-hour cooldown** (`self._exp_last_loss` dict): blocks re-entry on a pair for 4h after any exp_ loss
3. **Strategy-wide circuit breaker** (exp11, `self._exp_recent_losses` deque): after **2 exp_ losses in any rolling 1h window**, ALL new exp_ entries are blocked until the deque ages out. Protects against correlated failures on new pairs / new regimes. Constants: `_EXP_CB_WINDOW_HOURS=1`, `_EXP_CB_LOSS_THRESHOLD=2`.

Risk management for **non-exp** (x6_/x7_) trades:
- The class-level `stoploss = -0.10` (set in `NostalgiaScalpProX6X7Opt`) is **INERT** — both X6 and X7's `confirm_trade_exit` (`NostalgiaForInfinityX7.py:11598`) deny `stop_loss` and `trailing_stop_loss` in BOTH live and backtest, only allowing true liquidation crossings through. Backtest results show 0 stop_loss exits even on −50% trades.
- The synthetic backstop ladder in `NostalgiaScalpProX6X7Exp.custom_exit` is the actual loss floor, evaluated AFTER `super().custom_exit()` returns None: `1h/-15%`, `4h/-10%`, `12h/-5%`, `48h/any loss`. Exit reasons: `backstop_1h_15pct`, `backstop_4h_10pct`, `backstop_12h_5pct`, `backstop_48h_timeout`.
- **As of exp11, the backstop ladder applies to ALL trades** (including exp_) past the 60-min mark — closes the rare gap where an exp_ trade survives past its 120min timeout (only possible if profitable at 120min) and later turns red.
- A `30min/-10%` tier was added in exp10 but **reverted in exp11** after backtest showed it cut too many recoverable drawdowns: 19 backstop_30m_10pct firings vs 13 in exp9, dropping 6-month compounded profit from +120% to +87% (−33pp). The strategy's edge depends on letting -10% dips ride.
- `force_exit` is still the only `exit_reason` X7 lets through unconditionally — use `POST /api/v1/forceexit` for manual intervention.

Tag detection uses `_PFX_EXP in tag` (not `startswith`) — tag 705a can co-fire with X7 tags (e.g., `x7_61 exp_705a`); loss management must detect `exp_` anywhere in the tag string. `custom_exit` ordering: exp loss checks run BEFORE `super().custom_exit()`; backstop ladder runs AFTER (so X7's own exits take priority).

Cooldown state (`_exp_last_loss`, `_exp_recent_losses`) persists within a run but resets on container restart.

### Entry tag system

Each trade entry is tagged (e.g., `long_1`, `x7_45`, `x6_143`, `exp_705a`). Tags map to numbered conditions:
- X7 long: 1–13 normal, 21–26 pump, 41–53 quick, 501+ short
- ScalpPro active conditions: `4, 5, 42, 44, 45, 46, 61, 102, 104, 161, 162, 163`
- X6 safe additions: `62, 143`
- X5 addition: `41`

**WARNING on tags 62 and 143**: Only safe via X6's implementation. X7's versions produced -73% to -99% single-trade losses in bear markets. Never enable these in an X7-based strategy without a 5yr bear-market backtest.

**WARNING on tag x7_102**: The only losing tag in X6X7Exp (88.2% WR, avg -1.7%, worst -52.6% from BULLA force-exits). Consider disabling in future versions.

### Multi-timeframe indicator flow

Strategy loads 5m candles and fetches informative timeframes (15m, 1h, 4h, 1d) via `informative_pairs()`. Startup candle count is 800. All pairs must have 1d history at least 30 days before backtest start or the strategy crashes on `.diff()`.

### Position management (X7 / full NFI)

- `adjust_trade_position()` handles grinding (averaging down) and rebuying
- `custom_stake_amount()` controls dynamic sizing
- `custom_exit()` routes to mode-specific logic (grind, derisk, rapid, scalp, etc.)

ScalpPro / X6X7 strategies have **no DCA** — hard -10% stoploss only.

### Config layering

Standard backtest config stack (merged in order):
1. `NostalgiaForInfinity/configs/exampleconfig.json` — base (6 max trades, unlimited stake, dry_run)
2. `NostalgiaForInfinity/configs/trading_mode-futures.json` — futures overrides
3. `NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-available.json` — pairs with local data

Blacklist: `NostalgiaForInfinity/configs/blacklist-binance.json`

Key pairlist files:
- `pairlist-backtest-static-binance-futures-usdt-available.json` — **generated** by `download_candles.sh`; 150 pairs
- `pairlist-backtest-static-binance-futures-usdt-top100.json` — first 100 of the 150-pair list; used for fair Bybit comparison
- `pairlist-backtest-static-bybit-futures-usdt-available.json` — **generated** by `download_bybit_candles.sh`

### Per-month pair filtering (critical)

Each backtest script filters pairs per month before running. A pair is included only if its 4h feather file starts at least **20 days before the month's start date** (prevents `TypeError: NoneType - NoneType` in `informative_4h_indicators` at `.diff()`). Newer tokens are auto-included in later months once they accumulate enough history.

Pairs permanently excluded (no leverage tiers on Binance): KAT, CHIP, BSB, OPG, BASED, GENIUS, ROBO.

### Backtest results layout
```
user_data/backtest_results/
├── monthly/      # Binance monthly scripts
├── bybit/        # Bybit results
└── binance100/   # Binance top-100 results (fair Bybit vs Binance comparison)
```
Filename convention: `backtest_{STRATEGY}_{YYYYMM}.zip`. Results are `.zip` (freqtrade 2026.x) — use `--backtest-directory`, not `--export-filename`.

## Key constraints

- Never edit files in `NostalgiaForInfinity/` — upstream repo; edits will be overwritten by auto-update sidecar
- Timeframe must always be `5m`
- Backtest results are `.zip` — use `--backtest-directory`, not `--export-filename`
- Pairs without leverage tiers (KAT, CHIP, BSB, OPG, BASED, GENIUS, ROBO) crash freqtrade — keep them out of pairlists
- `startup_candle_count = 800` on 5m; pairs need 4h data starting ≥20 days before backtest start
- Use `20250101-` (not `20250401-`) when backtesting from Apr 2025 to satisfy the 20-day warmup check
- Never overwrite a live VPS config with a local dry_run config

## VPS live deployment

**Four managed live servers — all Tencent.** All run `NostalgiaScalpProX6X7Opt` (since 2026-05-17). Previously ran `NostalgiaScalpProX6X7Exp v26.05.16.exp11` (2026-05-16 → 2026-05-17). Use `docker compose restart` for strategy-only deploys; `docker compose up -d --force-recreate` when `docker-compose.yml` command line changes. The Alibaba VPS (`109.199.110.135`) that previously hosted `freqtrade_scalp` plus single-coin bots (ETH/XRP/SOL/XAUT/HYPE/mix) was retired 2026-05-15 — do not deploy or audit there.

| VPS | Exchange | Container | Role |
|-----|----------|-----------|------|
| `43.156.128.160` | Binance | `freqtrade_scalp_exp` | scalp dedicated |
| `43.128.72.96` | Binance | `freqtrade_scalp_copytrade` | Binance copytrade lead |
| `150.109.17.13` | Bybit | `freqtrade_scalp_bybit` | scalp dedicated |
| `129.226.90.189` | Bybit | `freqtrade_scalp_bybit_ct` | Bybit copytrade lead |

When deploying a strategy change, **deploy to ALL FOUR**; missing one leaves a stale bot running broken code in production (e.g. 2026-05-15 incident: backstop fix shipped to 3 VPS, `129.226.90.189` was missed and kept looping deny-exits on B/USDT until caught in audit).

### Tencent — Binance scalp (43.156.128.160)
SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.156.128.160`
Container: `freqtrade_scalp_exp`, dir `/opt/freqtrade_scalp/`, port 8092, Binance Futures, 2 vCPU / 2 GB RAM.
Dashboard: `http://43.156.128.160` (nginx on port 80 → proxies to 8092) — user: `freqtrader`, pass: `<DASHBOARD_PASS>`
- Port 8092 is bound to `127.0.0.1` only — not directly reachable from internet
- nginx at `/etc/nginx/sites-available/freqtrade`: rate limiting, PHP/exploit path blocking (`return 444`), bad UA dropping
- UFW: allows 22, 80, 443 only

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@43.156.128.160:/opt/freqtrade_scalp/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.156.128.160 \
  "cd /opt/freqtrade_scalp && sudo docker compose restart"
```

### Tencent — Binance copytrade lead (43.128.72.96)
SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.128.72.96`
Container: `freqtrade_scalp_copytrade`, dir `/opt/freqtrade_scalp/`, port 8092, Binance Futures, 2 vCPU / 2 GB RAM.
**Purpose:** dedicated lead-trader account for Binance copytrade product (separate Binance subaccount from `43.156.128.160`). Runs same `NostalgiaScalpProX6X7Exp` strategy with same chat_id (`1212757518`) but distinct telegram bot token and `bot_name: NFI_ScalpPro_CopyTrade`.
Dashboard: `http://43.128.72.96` (nginx on port 80 → proxies to 8092) — user: `freqtrader`, pass: `<DASHBOARD_PASS>`
- Port 8092 bound to `127.0.0.1` only — same nginx hardening (rate limits, PHP/exploit blocking, bad UA dropping) and UFW (22/80/443 only) as `43.156.128.160`
- Distinct `jwt_secret_key`: `<JWT_SECRET>`
- Provisioned 2026-05-07: Docker 29.4.3, Compose v5.1.3, nginx 1.24

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@43.128.72.96:/opt/freqtrade_scalp/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@43.128.72.96 \
  "cd /opt/freqtrade_scalp && sudo docker compose restart"
```

### Tencent — Bybit scalp (150.109.17.13)
SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@150.109.17.13`
Container: `freqtrade_scalp_bybit`, dir `/opt/freqtrade_scalp_bybit/`, port 8092, Bybit Futures, 2 vCPU / 2 GB RAM.
Dashboard: `http://150.109.17.13` (nginx on port 80 → proxies to 8092) — user: `freqtrader`, pass: `<DASHBOARD_PASS>`
- Port 8092 is bound to `127.0.0.1` only — not directly reachable from internet
- Bybit API key: `<BYBIT_API_KEY>` (IP `150.109.17.13` must be whitelisted in Bybit API settings)
- **Note**: If bot fails to start with `retCode 10010 "Unmatched IP"`, re-confirm `150.109.17.13` in Bybit API key settings

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@150.109.17.13:/opt/freqtrade_scalp_bybit/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@150.109.17.13 \
  "cd /opt/freqtrade_scalp_bybit && sudo docker compose restart"
```

### Tencent — Bybit copytrade lead (129.226.90.189)
SSH: `sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@129.226.90.189`
Container: `freqtrade_scalp_bybit_ct`, dir `/opt/freqtrade_scalp_bybit/`, port 8092, Bybit Futures, 2 vCPU / 2 GB RAM.
**Purpose:** dedicated lead-trader account for Bybit copytrade product (separate Bybit subaccount from `150.109.17.13`). Same `NostalgiaScalpProX6X7Exp` strategy, shared telegram chat_id `1212757518` but distinct bot token and `bot_name: NFI_ScalpPro_Bybit_CopyTrade`.
Dashboard: `http://129.226.90.189` (nginx on port 80 → proxies to 8092) — user: `freqtrader`, pass: `<DASHBOARD_PASS>`
- Port 8092 bound to `127.0.0.1` only — same nginx hardening (rate limits, `@fs`/`%40fs`/`passwd`/`shadow`/`proc-self` blocking, PHP/exploit path blocking, bad UA dropping) and UFW (22/80/443 only) as the other VPS
- Bybit API key: `<BYBIT_API_KEY>` — IP `129.226.90.189` must be whitelisted in Bybit API settings (failure mode: `retCode 10010 "Unmatched IP"`)
- Distinct `jwt_secret_key` (64-hex) and `ws_token` (48-hex); API password `<DASHBOARD_PASS>`
- Provisioned 2026-05-10: Docker 29.4.3, Compose v5.1.3, nginx 1.24, Fail2Ban 1.0.2 (Ubuntu 24.04)
- nginx config here also includes the `@fs/CVE` blocking missing on the older three VPS

Deploy:
```bash
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@129.226.90.189:/opt/freqtrade_scalp_bybit/user_data/strategies/
sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@129.226.90.189 \
  "cd /opt/freqtrade_scalp_bybit && sudo docker compose restart"
```

### VPS security notes
- Docker port binding must be `"127.0.0.1:8092:8092"` in `docker-compose.yml` — never `"8092:8092"` (bypasses UFW)
- After any `docker-compose.yml` port change, use `docker compose up -d --force-recreate` (not `restart`)
- nginx config blocks: `.php`/`.phtml` paths, `eval-stdin`/`invokefunction`/`pearcmd`/`phpunit` patterns, `.git`/`.env`/`wp-admin`; returns 444 (silent drop)
- To access API directly from local machine via SSH tunnel: `ssh -L 8092:127.0.0.1:8092 ubuntu@150.109.17.13 -N`
- **fail2ban** runs on every VPS with 3 jails: `sshd` (maxretry=6), `nginx-http-auth`, `nginx-limit-req` (maxretry=10). Bantime 1h, findtime 10m, backend=systemd, banaction=nftables. Whitelist `127.0.0.1/8 ::1 <HOME_IP>` (home IP) — keep your office/home IP whitelisted to avoid lockout. Config at `/etc/fail2ban/jail.local`.
- **Provisioning a new VPS — security checklist** (must do all):
  1. UFW: deny incoming, allow 22/80/443 only
  2. nginx as reverse proxy on :80 with rate-limit + UA-block + exploit-path-block config
  3. Docker port bound `127.0.0.1:8092:8092` (NOT `8092:8092`)
  4. nginx site config + symlink in `sites-enabled/`, remove default
  5. fail2ban: install + push `jail.local` + enable + restart
  6. Distinct `jwt_secret_key` per VPS (don't reuse across hosts)

### Live VPS pairlist & blacklist

Both Tencent VPS use a **dynamic** `VolumePairList` — the static `pair_whitelist` in `config.json` contains only `BTC/USDT:USDT`; pairs are picked at runtime by exchange volume.

Pipeline: `VolumePairList` (top 90 by quoteVolume, refresh ~63 min) → `FullTradesFilter` → `AgeFilter` (≥60 days listed) → `PriceFilter` (≥0.3%) → `SpreadFilter` (≤0.5%) → `RangeStabilityFilter` (3-day RoC 0.03–2.0) → `VolumePairList` (final top 75).

**Live `pair_blacklist` regex** (must reject commodities/stocks/leveraged tokens that the volume sort would otherwise admit):
- Commodities: `(XAU|XAUT|XAG|OIL|GAS|PAXG)/.*`
- Stocks: `(TSLA|AAPL|MSTR|GOOGL|AMZN|NVDA|COIN|INTC|CRCL)/.*`
- Leveraged tokens: `.*(_PREMIUM|BEAR|BULL|HALF|HEDGE|UP|DOWN|[1235][SL])/.*`
- Fiat quote: `(ARS|AUD|BIDR|BRZ|BRL|CAD|CHF|EUR|GBP|HKD|IDRT|JPY|NGN|PLN|RON|RUB|SGD|TRY|UAH|USD|ZAR)/.*`
- Stablecoin pairs: `(AEUR|FDUSD|BUSD|CUSD|CUSDT|DAI|AXG|SUSD|TUSD|USDC|USDN|USDP|USDT|VAI|UST|USTC|AUSD|FDUSD|EURI|USDS|XUSD|USD1|RLUSD|U)/.*`
- Explicit no-leverage-tier pairs (also crash freqtrade): `KAT`, `CHIP`, `BSB`, `OPG`, `BASED`, `ROBO`, `GENIUS`
- Tencent Binance also blacklists: `AIOT`, `BLESS`

**Maintenance protocol:** When Binance/Bybit launch new tokenized stocks or commodity pairs, they can enter the dynamic top-75 by volume before the regex catches them. Verify with `curl -s -u freqtrader:<DASHBOARD_PASS> http://127.0.0.1:8092/api/v1/whitelist` (over SSH tunnel) and extend the regex if needed. Confirmed incidents: 2026-05-06 — XAU (gold spot), INTC (Intel stock), CRCL (Circle stock) snuck into Tencent Binance live whitelist; regex extended.

## Backtest result benchmarks

Run `python3 user_data/scripts/summarize_monthly.py` for current results. Historical aggregates for reference:

| Strategy | Period | Exchange | Trades | WR% | Compounded | Worst DD |
|----------|--------|----------|--------|-----|------------|---------|
| NostalgiaForInfinityX7 | Apr25–Apr26 (12mo) | Binance 85-113P | 391 | 97.2% | +5,416% | 19.11% (Oct25) |
| NostalgiaScalpPro | Apr24–Mar26 (24mo) | Binance ~90P | 512 | 99.4% | +29,789% | 11.48% (Apr24 only) |
| NostalgiaScalpProOptimized | Apr25–Apr26 (12mo) | Binance ~90P | 102 | 100% | +1,138% | 0% |
| NostalgiaScalpPro150 | Apr25–Apr26 (12mo) | Binance 150P | 188 | 97.9% | +518% | 39.47% (Mar26) |
| NostalgiaScalpPro | Jan24–Mar26 (27mo) | Binance top-100 | 204 | 99.0% | +868% | 3.89% |
| NostalgiaScalpPro | Jan24–Mar26 (27mo) | Bybit top-100 | 214 | 99.5% | +909% | 11.02% |
| NostalgiaScalpProX6X7 | Jan24–Mar26 (27mo) | Binance top-100 | 296 | 99.3% | +4,439% | 2.22% |
| NostalgiaScalpProX6X7Exp (exp9, stale pairlist) | Jan24–Apr26 (28mo) | Binance top-100 | 331 | 99.4% | +8,095% | 7.64% |
| NostalgiaScalpProX6X7Exp (exp11) | Mar24–May26 (27mo) | Binance top-100 (refreshed 2026-05-16) | 272 | 87.5% | +969.94% | 17.82% (Apr24) |
| **NostalgiaScalpProX6X7Opt** | **Dec25–May26 (6mo)** | **Binance top-100 (refreshed 2026-05-16)** | **78** | **98.7%** | **+199.19%** | **1.19% (May26)** |
| NostalgiaScalpProX6X7Exp (exp11) | Dec25–May26 (6mo) | Binance top-100 (refreshed 2026-05-16) | 80 | 82.5% | +117.69% | 7.50% (Dec25) |
| NostalgiaForInfinityX5 | May21–Mar26 (59mo) | Binance top-100 | 1,245 | 94.4% | +149,656% | 58.59% |

### Latest backtest comparison — X6X7Opt vs X6X7Exp (last 6 months)

**Last run: 2026-05-17.** Binance top-100 pairlist (refreshed 2026-05-16), data through 2026-05-16 23:25 UTC. Same pairlist + same per-month filter for both strategies.

| Month  | Opt T | Opt WR | Opt P%   | Opt DD | Exp T | Exp WR | Exp P%   | Exp DD | ΔP%     |
|--------|------:|-------:|---------:|-------:|------:|-------:|---------:|-------:|--------:|
| 202512 |    16 | 100.0% | +11.58%  |  0.00% |    16 |  62.5% |  −1.62%  |  7.50% | −13.20% |
| 202601 |     1 | 100.0% |  +0.53%  |  0.00% |     1 | 100.0% |  +0.53%  |  0.00% |   0.00% |
| 202602 |    17 | 100.0% | +24.57%  |  0.00% |    19 |  78.9% | +15.96%  |  4.35% |  −8.62% |
| 202603 |     7 | 100.0% |  +9.04%  |  0.00% |     7 | 100.0% |  +9.04%  |  0.00% |   0.00% |
| 202604 |    24 | 100.0% | +63.76%  |  0.00% |    24 |  91.7% | +52.15%  |  2.85% | −11.60% |
| 202605 |    13 |  92.3% | +19.93%  |  1.19% |    13 |  84.6% | +14.42%  |  2.59% |  −5.51% |

**Aggregate (6 months):** Opt 77W/1L (98.7% WR, compounded +199.19%, worst-DD 1.19%, 0 losing months) vs Exp 66W/14L (82.5% WR, compounded +117.69%, worst-DD 7.50%, 1 losing month — Dec'25). The 81pp gap is entirely the backstop ladder: every Exp loss is a `backstop_*` exit on x6_/x7_ trades that X6X7Opt held (and either recovered, or ended with a smaller force_exit at end-of-data). The `exp_705a` tag did not fire once in this window (WILLR + green-candle filters), so the Exp wrapper added pure cost without offsetting tail-event prevention.

**Per-month notes:**
- **Dec'25** (−13.20pp gap): same 16 entries; Exp backstopped 6 (MON, UNI, LDO, ARB×2, DOGS); Opt held all to recovery.
- **Jan'26** (0pp): 1 trade (BTC), identical for both.
- **Feb'26** (−8.62pp): COLLECT alone triggered 3 Exp backstops (−16.95%, −16.09%, −15.59%); plus UNI −13.20% backstop.
- **Mar'26** (0pp): 7 trades each, no backstops fired.
- **Apr'26** (−11.60pp, both strategies' best month): Exp lost on SAGA (`backstop_1h_15pct` −15.73%) and AKE (`backstop_1h_15pct` −17.28%); Opt held both.
- **May'26** (−5.51pp, partial through May 16 23:25): Exp lost on SKYAI (`backstop_1h_15pct` −15.68%) and AIO (`backstop_4h_10pct` −12.05%); Opt lost only on AIO (`force_exit` −7.23% at end-of-data).

Decision (2026-05-17): switched all 4 Tencent VPS from X6X7Exp → X6X7Opt. Rollback to Exp if a stress regime returns (Mar 2026-style cascade or Apr 2024-style force-exits) and the backstops start saving trades.

**Exchange comparison (12-month Apr25–Mar26):** Bybit-100 +252%, Binance-100 +260%, Binance-150 +518% (but 39% DD spike — not suitable for live). Binance-100 recommended for live: better DD control (2.13% worst month).

**Binance-150 vs Binance-90:** More trades but Mar26 DD spike (39.47%) from lower-liquidity pairs. Stick with 90-pair `NostalgiaScalpProOptimized` for live trading.

**Stale-pairlist note (X6X7Exp +8,095% line):** The 99.4% WR / 7.64% DD benchmark was run with a pairlist snapshot from ~Apr 2025. The 2026-05-16 refresh (today's volume-sorted top-100 including HYPE, AIGENSYN, IRYS, SAGA, FARTCOIN, PENGU, etc.) reproduced the same strategy at +969.94% / 87.5% WR / 17.82% DD — the entire gap is Apr 2024, where pairs like WLD/SUI/FIL/ADA/APT on x6_62/x6_143 produced -16% to -44% losses that the older pairlist didn't have in its universe at the time. The strategy itself is unchanged; the pairlist composition is the variable. Use the +970% figure for fair forward-looking expectations on a current-volume basis.
