# ft_scalp — NostalgiaForInfinity X6/X7 Scalp Strategy

A high-win-rate cryptocurrency scalp trading strategy. Currently deployed live on Binance & Bybit futures across 4 production VPS.

**Headline numbers — current live strategy (X6X7Opt), last 6 months (Dec 2025 – May 16 2026), Binance top-100 by volume (last run 2026-05-17):**

| Metric | Value |
|---|---:|
| Trades | 78 |
| Win rate | 98.7% |
| **Compounded profit** | **+199.19%** |
| $10k → | $29,919 |
| Worst single month | +0.53% (Jan 2026) |
| Worst max drawdown | 1.19% (May 2026) |
| Losing months | 0 |
| Best month | +63.76% (Apr 2026) |

For longer-horizon historical numbers on the previous live strategy (X6X7Exp), see [CLAUDE.md](./CLAUDE.md) — 27-month Mar 2024 – May 16 2026 aggregate was +969.94% / 87.5% WR / 17.82% worst-DD on Exp. The Dec 2025 – May 2026 backtest that motivated the 2026-05-17 switch back to Opt is summarized in [Backtest results](#backtest-results) below.

> **Disclaimer.** Past performance does not predict future results. Crypto futures trading carries substantial risk of loss. This code is provided as-is for educational and research use. You assume all responsibility for any trading you perform.

---

## Table of contents

1. [What this is](#what-this-is)
2. [Quick start](#quick-start)
3. [Strategy architecture](#strategy-architecture)
4. [Risk management](#risk-management)
5. [Backtest workflow](#backtest-workflow)
6. [Backtest results](#backtest-results)
7. [Live deployment](#live-deployment)
8. [Project layout](#project-layout)
9. [Configuration](#configuration)
10. [Pairlist & blacklist](#pairlist--blacklist)
11. [Development notes](#development-notes)
12. [History](#history)

---

## What this is

`ft_scalp` is a **mean-reversion scalp** strategy that combines:

- **X6 child** (`NostalgiaForInfinityX6`) — runs only tags 62 & 143 (the X6 implementations of these tags are provably safer than X7's — historical worst-case −0.54% vs X7's −99%).
- **X7 child** (`NostalgiaScalpProOptimized`) — runs the 12 ScalpPro tags (4, 5, 41, 42, 44, 45, 46, 61, 102, 104, 161, 162, 163). Same set as the classic `NostalgiaScalpPro` strategy but with ~40% fewer indicator columns.
- **Experimental tag 705a** (`NostalgiaScalpProX6X7Exp`) — MFI Volume Capitulation, layered on top of the X6+X7 wrapper.

Each entry tag is **prefixed** to identify its parent (e.g., `x6_62`, `x7_45`, `exp_705a`). Exits route back to the originating child — X6 entries get X6 exits, X7 entries get X7 exits, no mixing.

- **Long-only**, **no DCA**, **no grinding**, **futures USDT-margined** on Binance and Bybit.
- **Timeframe: 5m**. Informative: 15m, 1h, 4h, 1d.
- **Hard floor**: backstop ladder in `custom_exit` (the class-level `stoploss = -0.10` is inert because X7's `confirm_trade_exit` denies it — see [Risk management](#risk-management)).

The current live strategy is **`NostalgiaScalpProX6X7Opt`** (deployed 2026-05-17 across all 4 VPS). The previous live strategy `NostalgiaScalpProX6X7Exp v26.05.16.exp11` (2026-05-16 → 2026-05-17) remains on each VPS for rollback — see [Backtest results](#backtest-results) for the comparison that drove the switch.

---

## Quick start

### Prerequisites

- Python 3.12+
- freqtrade (tested with 2026.2-dev / 2026.4)
- The upstream strategy repo checked out alongside this one (see [Setup](#setup))

### Setup

```bash
# Clone this repo
git clone https://github.com/gattack/ft_scalp.git
cd ft_scalp

# Clone NostalgiaForInfinity into the project (auto-updated upstream)
git clone https://github.com/iterativv/NostalgiaForInfinity.git

# Create venv & install freqtrade
python3 -m venv .venv
source .venv/bin/activate
pip install freqtrade
```

### Download historical data

```bash
# Top 150 Binance pairs, 2 years of history
bash user_data/scripts/download_candles.sh 150 20240101-

# Or for Bybit (separate dir, won't overwrite Binance)
bash user_data/scripts/download_bybit_candles.sh 100 20210101-
```

### Run a backtest

```bash
# Single month
freqtrade backtesting \
  --config NostalgiaForInfinity/configs/exampleconfig.json \
  --config NostalgiaForInfinity/configs/trading_mode-futures.json \
  --config NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-top100.json \
  --strategy NostalgiaScalpProX6X7Exp \
  --strategy-path user_data/strategies \
  --timerange 20260401-20260501 \
  --datadir NostalgiaForInfinity/user_data/data \
  --export trades \
  --backtest-directory user_data/backtest_results/binance100 \
  --cache day

# Monthly across 27 months (Mar 2024 → May 2026)
bash user_data/scripts/run_binance100_backtest.sh NostalgiaScalpProX6X7Exp

# Summarize results
python3 user_data/scripts/summarize_monthly.py \
  --strategy NostalgiaScalpProX6X7Exp \
  --results-dir user_data/backtest_results/binance100
```

---

## Strategy architecture

### Inheritance chain

```
IStrategy (freqtrade base)
└── NostalgiaScalpProX6X7Opt  ← LIVE BOT (since 2026-05-17)
    │   • Multi-child wrapper instantiating two NFI strategies
    │   • _x6 = NostalgiaForInfinityX6 (restricted to tags 62, 143)
    │   • _x7 = NostalgiaScalpProOptimized (12 ScalpPro tags)
    │   • populate_entry_trend merges signals, prefixes tags x6_/x7_
    │   • Exit callbacks strip prefix and delegate to originating child
    │   • No synthetic backstops — losses are decided entirely by the child that owns the trade
    └── NostalgiaScalpProX6X7Exp  (previously live 2026-05-16 → 2026-05-17; kept for rollback)
        • Adds entry tag 705a (MFI Volume Capitulation)
        • Adds progressive loss-cut for exp_ trades
        • Adds per-pair cooldown + strategy-wide circuit breaker
        • Adds backstop ladder for non-exp losers
```

### Multi-child mechanics

The trickiest part of this strategy is the **multi-child architecture** in `NostalgiaScalpProX6X7Opt`:

- **Indicators**: `populate_indicators` runs `NostalgiaScalpProOptimized` only (X7 is a strict superset of what X6 tags 62/143 need).
- **Entries**: `populate_entry_trend` invokes both children on the enriched dataframe, filters each to its allowed tag set, and prefixes tags. **Priority: X6 > X7** (X6 entries overwrite X7 on the same candle — X6 is more conservative).
- **Exits**: `custom_exit`, `confirm_trade_exit`, `order_filled` all detect the tag prefix, strip it, and delegate to the originating child. No mixing across children.
- **Tag patching context manager**: child strategies inspect other open trades' `enter_tag` for grind/rebuy slot logic. Before each child callback, `_patch_tags()` strips prefixes from all open trades temporarily, then restores them.

### Entry tag system

| Tag prefix | Source | Allowed tags |
|---|---|---|
| `x6_` | `NostalgiaForInfinityX6` | `62`, `143` |
| `x7_` | `NostalgiaScalpProOptimized` | `4, 5, 41, 42, 44, 45, 46, 61, 102, 104, 161, 162, 163` |
| `exp_` | `NostalgiaScalpProX6X7Exp` | `705a` (can co-fire with x7_, producing combined tags like `x7_61 exp_705a`) |

**Warnings**:

- **Tags 62 and 143 are ONLY safe via X6's implementation.** X7's versions of these tags produced −73% to −99% single-trade losses in bear markets. Never enable them in an X7-based strategy without a 5-year bear-market backtest.
- **Tag x7_102** has been a chronic underperformer (88.2% WR in long-window backtests, avg −1.7%, worst −52.6%). Candidate for removal in future versions.

### Tag 705a (exp_) — entry conditions

The experimental MFI Volume Capitulation tag, layered on top of X6X7Opt:

```python
RSI_3 < 40  AND  MFI_14_1h < 20  AND  RSI_3_15m < 10  AND
close < EMA_12 * 0.95  AND  AROONU_14 < 25  AND
STOCHRSIk_14_14_3_3_15m < 20  AND  WILLR_14 < -80  AND
close > open * 1.01   # green candle bounce confirmation
```

Filter history:
- `WILLR_14 < -80` (added in earlier iteration) removed 3 of 4 historical catastrophic losses (CRV/DYDX/ARB Apr 2024 force-exits).
- `close > open * 1.01` (exp9) removed 9 of 10 remaining red-body losses while preserving ~95% WR.

---

## Risk management

This is the most important section of the strategy. The interaction between class-level stoploss, X7's `confirm_trade_exit`, and the synthetic backstop ladder is non-obvious.

### The dead class stoploss

`NostalgiaScalpProX6X7Opt` declares `stoploss = -0.10`. **This stoploss never fires.** Both X6 and X7's `confirm_trade_exit` deny `stop_loss` and `trailing_stop_loss` in **both live and backtest** (only true liquidation crossings get through). The class attribute is kept at `-0.10` so freqtrade's config validation passes; the actual loss floor is implemented in `custom_exit`.

### Backstop ladder (non-exp & long-running exp_ trades)

Evaluated AFTER `super().custom_exit()` returns None — so the parent X7 profit-taking logic always gets first refusal. The ladder:

| Trigger | Exit reason |
|---|---|
| `trade_age ≥ 1h` and `profit ≤ −15%` | `backstop_1h_15pct` |
| `trade_age ≥ 4h` and `profit ≤ −10%` | `backstop_4h_10pct` |
| `trade_age ≥ 12h` and `profit ≤ −5%` | `backstop_12h_5pct` |
| `trade_age ≥ 48h` and `profit < 0` | `backstop_48h_timeout` |

These tiers apply to **all trades** (including exp_ trades alive past the 60-min mark) so long-running exp_ trades that survive their 120min timeout window and later turn red are also caught.

### Exp_ progressive loss cuts (tighter, exp_ trades only)

Evaluated BEFORE `super().custom_exit()` so they fire first on exp_ trades:

| Trigger | Exit reason |
|---|---|
| `trade_age ≥ 10min` and `profit < −5%` | `exp_cut_5pct` |
| `trade_age ≥ 15min` and `profit < −3%` | `exp_cut_3pct` |
| `trade_age ≥ 30min` and `profit < −2%` | `exp_cut_2pct` |
| `trade_age ≥ 60min` and `profit < −1%` | `exp_cut_1pct` |
| `trade_age ≥ 120min` and `profit < 0` | `exp_timeout_exit` |

Winners typically resolve in <78 min; losers that don't bounce get cut early.

### Cooldowns

- **Per-pair**: 4h after any exp_ loss on a pair, new exp_ entries on that pair are blocked.
- **Strategy-wide circuit breaker** (added in exp11): after **2 exp_ losses in any rolling 1-hour window**, ALL new exp_ entries are blocked until the deque ages out. Protects against correlated regime failures (e.g., a sudden flash crash triggering 705a entries across many pairs simultaneously).

State persists within a run but resets on container restart.

### What's been tried and rejected

The development history is documented in [CLAUDE.md](./CLAUDE.md). One notable experiment: **exp10** added a `30min/-10%` backstop tier intended to cap worst losses. In a 6-month backtest, this fired 19 times vs 13 backstop exits in exp9, dropping compounded profit from +120% to +87% (−33pp) — too many recoverable drawdowns got killed. **Reverted in exp11.** The strategy's edge depends on letting -10% intra-trade drawdowns ride.

---

## Backtest workflow

### Monthly per-pair filter (critical)

Each backtest run filters the pairlist per-month: a pair is included only if its 4h feather file starts at least **20 days before the month's start date**. This prevents `TypeError: NoneType - NoneType` in `informative_4h_indicators` at `.diff()`. Newer tokens automatically join the universe in later months as they accumulate enough history.

### Pairs permanently excluded

Pairs that have no leverage tiers on Binance Futures and cause freqtrade to crash on startup:

```
KAT, CHIP, BSB, OPG, BASED, GENIUS, ROBO, EDGE
```

Plus tokenized stocks / commodities / leveraged tokens / fiat-quoted / stablecoin pairs — see `user_data/scripts/_filter_pairlist.py` and `NostalgiaForInfinity/configs/blacklist-binance.json`.

### Backtest scripts

| Script | Window | Strategy default | Notes |
|---|---|---|---|
| `run_monthly_backtests.sh` | Apr 2025 – Apr 2026 (12mo) | X7 | One zip per month |
| `run_2year_backtest.sh` | Apr 2024 – Apr 2026 (24mo) | ScalpPro | |
| `run_5year_backtest.sh` | Apr 2021 – Apr 2026 (60mo) | ScalpPro | |
| `run_bybit_5year_backtest.sh` | Apr 2021 – Apr 2026 (60mo) | ScalpPro | Bybit data dir |
| `run_binance100_backtest.sh` | Jan 2024 – May 2026 (28mo) | ScalpPro | Apples-to-apples vs Bybit top-100 |
| `run_150pairs_backtest.sh` | 150-pair variant | ScalpPro150 | |
| `run_2024_backtests.sh` | Apr 2024 – Apr 2025 (12mo) | ScalpPro | Historical year |

All scripts skip months that already have a results zip, so re-runs are idempotent.

### Result analysis

```bash
# Summary table across all monthly zips
python3 user_data/scripts/summarize_monthly.py \
  --strategy NostalgiaScalpProX6X7Exp \
  --results-dir user_data/backtest_results/binance100

# Per-entry-tag stats (which conditions to disable)
python3 user_data/scripts/analyze_tags.py \
  --strategy NostalgiaScalpProX6X7Exp \
  --min-trades 5 \
  --results-dir user_data/backtest_results/binance100
```

---

## Backtest results

**Last run: 2026-05-17.** Binance top-100 pairlist (refreshed 2026-05-16), data through 2026-05-16 23:25 UTC. Same pairlist + same per-month filter for both strategies.

### X6X7Opt vs X6X7Exp — Dec 2025 → May 16 2026 (per-month)

| Month  | Opt T | Opt WR | Opt P%   | Opt DD | Exp T | Exp WR | Exp P%   | Exp DD | ΔP%     |
|--------|------:|-------:|---------:|-------:|------:|-------:|---------:|-------:|--------:|
| 202512 |    16 | 100.0% | +11.58%  |  0.00% |    16 |  62.5% |  −1.62%  |  7.50% | −13.20% |
| 202601 |     1 | 100.0% |  +0.53%  |  0.00% |     1 | 100.0% |  +0.53%  |  0.00% |   0.00% |
| 202602 |    17 | 100.0% | +24.57%  |  0.00% |    19 |  78.9% | +15.96%  |  4.35% |  −8.62% |
| 202603 |     7 | 100.0% |  +9.04%  |  0.00% |     7 | 100.0% |  +9.04%  |  0.00% |   0.00% |
| 202604 |    24 | 100.0% | +63.76%  |  0.00% |    24 |  91.7% | +52.15%  |  2.85% | −11.60% |
| 202605 |    13 |  92.3% | +19.93%  |  1.19% |    13 |  84.6% | +14.42%  |  2.59% |  −5.51% |

### Aggregate (6 months)

| Metric            | X6X7Opt        | X6X7Exp        |
|-------------------|---------------:|---------------:|
| Trades            | 78             | 80             |
| Wins / Losses     | 77 / 1         | 66 / 14        |
| Win rate          | 98.7%          | 82.5%          |
| Compounded profit | **+199.19%**   | **+117.69%**   |
| $10k →            | $29,919        | $21,769        |
| Worst month DD    | 1.19% (May'26) | 7.50% (Dec'25) |
| Losing months     | 0              | 1 (Dec'25)     |

**Why the gap.** Every Exp loss in this window is a `backstop_*` exit on an x6_/x7_ trade. In Opt, those same trades either recovered (X7's `confirm_trade_exit` denies `stop_loss` — they sit until profit-take or natural exit) or hit `force_exit` at end-of-data with a smaller loss (e.g. AIO/USDT on May 16: Opt `force_exit` −7.23% vs Exp `backstop_4h_10pct` −12.05%). The `exp_705a` tag did not fire once in this window — its WILLR-80 + green-candle filters were not satisfied — so the Exp wrapper contributed pure cost without offsetting tail-event prevention.

**Caveat.** This 6-month sample has no tail events of the type the backstops are designed to catch (no Mar 2026-style cascade, no Apr 2024-style force-exits). The 28-month historical aggregate showed +8,095% on Exp vs ~2,500% on Opt — Exp's edge came specifically from Apr 2024 and Mar 2026. If a stress regime returns, roll back to Exp.

### Reproduce

```bash
# Refresh top-100 data through today
freqtrade download-data \
  --config NostalgiaForInfinity/configs/exampleconfig.json \
  --config NostalgiaForInfinity/configs/trading_mode-futures.json \
  --config NostalgiaForInfinity/configs/pairlist-backtest-static-binance-futures-usdt-top100.json \
  --timerange 20251101- --timeframes 5m 15m 1h 4h 1d \
  --trading-mode futures --datadir NostalgiaForInfinity/user_data/data

# Run both strategies across the same 6 months
bash user_data/scripts/run_binance100_backtest.sh NostalgiaScalpProX6X7Opt
bash user_data/scripts/run_binance100_backtest.sh NostalgiaScalpProX6X7Exp

# Summarize
python3 user_data/scripts/summarize_monthly.py \
  --strategy NostalgiaScalpProX6X7Opt --results-dir user_data/backtest_results/binance100
python3 user_data/scripts/summarize_monthly.py \
  --strategy NostalgiaScalpProX6X7Exp --results-dir user_data/backtest_results/binance100
```

---

## Live deployment

The strategy runs on 4 production VPS (all Tencent Cloud). All four run **the same** `NostalgiaScalpProX6X7Opt` strategy (since 2026-05-17) on a dynamic top-75 by volume pairlist with multi-stage filters. Previously ran `NostalgiaScalpProX6X7Exp v26.05.16.exp11` from 2026-05-16 to 2026-05-17.

| VPS | Exchange | Container | Role |
|---|---|---|---|
| `<BINANCE_SCALP_IP>` | Binance | `freqtrade_scalp_exp` | scalp dedicated |
| `<BINANCE_COPYTRADE_IP>` | Binance | `freqtrade_scalp_copytrade` | Binance copytrade lead |
| `<BYBIT_SCALP_IP>` | Bybit | `freqtrade_scalp_bybit` | scalp dedicated |
| `<BYBIT_COPYTRADE_IP>` | Bybit | `freqtrade_scalp_bybit_ct` | Bybit copytrade lead |

(Actual IPs / credentials are in `.credentials.local`, not committed.)

### Deploy a strategy update

When you change `NostalgiaScalpProX6X7Exp.py` or its parents, deploy to **all 4 VPS** — missing one leaves a stale bot looping broken code (2026-05-15 incident: missed `<BYBIT_COPYTRADE_IP>` and it kept deny-exiting B/USDT for hours until caught in audit).

Template (replace placeholders from `.credentials.local`):

```bash
# For each VPS
sshpass -p "<VPS_SSH_PASSWORD>" scp -o StrictHostKeyChecking=no \
  user_data/strategies/NostalgiaScalpProX6X7Exp.py \
  user_data/strategies/NostalgiaScalpProX6X7Opt.py \
  user_data/strategies/NostalgiaScalpProOptimized.py \
  user_data/strategies/NostalgiaForInfinityX6.py \
  user_data/strategies/NostalgiaForInfinityX7.py \
  ubuntu@<VPS_IP>:<REMOTE_DIR>/user_data/strategies/

sshpass -p "<VPS_SSH_PASSWORD>" ssh -o StrictHostKeyChecking=no ubuntu@<VPS_IP> \
  "cd <REMOTE_DIR> && sudo docker compose restart"
```

Use `docker compose up -d --force-recreate` instead of `restart` when `docker-compose.yml` (e.g. port bindings) has changed.

### VPS security baseline

Each VPS hardened with:
- `UFW`: deny incoming, allow 22 / 80 / 443 only
- `nginx` reverse proxy on :80 → freqtrade on `127.0.0.1:8092`, with rate limiting, PHP/exploit path blocking (`return 444`), bad-UA dropping, `@fs`/CVE blocks
- `fail2ban`: 3 jails (`sshd` maxretry=6, `nginx-http-auth`, `nginx-limit-req` maxretry=10), bantime 1h, findtime 10m, home IP allowlisted
- Distinct `jwt_secret_key` per VPS
- Docker port binding `127.0.0.1:8092:8092` (NOT `8092:8092` — would bypass UFW)

---

## Project layout

```
ft_scalp/
├── README.md                   # this file
├── CLAUDE.md                   # detailed context for Claude Code agents (sanitized)
├── AGENTS.md                   # parallel quick-reference for OpenCode agents (sanitized)
├── .gitignore
├── .credentials.local          # gitignored — live credentials
├── user_data/
│   ├── strategies/
│   │   ├── NostalgiaScalpProX6X7Exp.py    # live bot
│   │   ├── NostalgiaScalpProX6X7Opt.py    # multi-child wrapper (parent)
│   │   ├── NostalgiaScalpProOptimized.py  # X7 with reduced indicator columns
│   │   ├── NostalgiaForInfinityX6.py      # local copy of upstream X6
│   │   ├── NostalgiaForInfinityX7.py      # local copy of upstream X7
│   │   ├── NostalgiaForInfinityX5.py      # older version, for comparison
│   │   ├── NostalgiaScalpPro.py           # direct X7-based scalp (no wrapper)
│   │   └── ...other variants
│   └── scripts/
│       ├── download_candles.sh
│       ├── download_bybit_candles.sh
│       ├── _filter_pairlist.py            # strip stocks/commodities/leveraged tokens
│       ├── run_monthly_backtests.sh
│       ├── run_binance100_backtest.sh
│       ├── summarize_monthly.py
│       └── analyze_tags.py
└── NostalgiaForInfinity/       # NOT included — clone separately from upstream
    └── configs/                # config templates (referenced by --config)
```

### NostalgiaForInfinity directory

The upstream NFI repo is **not committed** in `ft_scalp`. Clone it alongside:

```bash
cd <your-projects-dir>
git clone https://github.com/iterativv/NostalgiaForInfinity.git
```

Local strategies reference `NostalgiaForInfinity/configs/*.json` via `--config` and import upstream X5/X6/X7 modules (also kept in `user_data/strategies/` as local copies for stability — when upstream changes break the multi-child wrapper, we pin against the local copies).

---

## Configuration

### Config layer stack

Backtests merge 3+ configs in order:

1. **`exampleconfig.json`** — base (6 max trades, unlimited stake, dry_run=true, 5m timeframe, futures order types, limit-pricing)
2. **`trading_mode-futures.json`** — `trading_mode: futures`, `margin_mode: isolated`, `dataformat: feather`
3. **`pairlist-backtest-static-binance-futures-usdt-top100.json`** — static whitelist of 100 pairs
4. (per-month filtered pairlist written to a temp file by the wrapper scripts)

### Effective merged config

```
exchange.name      : binance / bybit
trading_mode       : futures
margin_mode        : isolated
stake_currency     : USDT
stake_amount       : unlimited
max_open_trades    : 6
tradable_balance_ratio: 0.99
timeframe          : 5m
startup_candle_count: 800
dataformat         : feather
entry_pricing      : limit at order_book top
exit_pricing       : limit at order_book top
position_adjustment_enable: false   (no DCA / grinding)
can_short          : false
```

---

## Pairlist & blacklist

### Live (production VPS)

Dynamic `VolumePairList` with multi-stage filters:

```
VolumePairList (top 90 by quoteVolume, refresh ~63 min)
  → FullTradesFilter
  → AgeFilter (≥60 days listed)
  → PriceFilter (≥0.3%)
  → SpreadFilter (≤0.5%)
  → RangeStabilityFilter (3-day RoC 0.03–2.0)
  → VolumePairList (final top 75)
```

### Blacklist regex (live)

Must exclude pairs that the volume sort would otherwise admit:

- Commodities: `(XAU|XAUT|XAG|OIL|GAS|PAXG)/.*`
- Tokenized stocks: `(TSLA|AAPL|MSTR|GOOGL|AMZN|NVDA|COIN|INTC|CRCL|MU|BILL|EWY|QQQ|INX|...)/.*`
- Leveraged tokens: `.*(_PREMIUM|BEAR|BULL|HALF|HEDGE|UP|DOWN|[1235][SL])/.*`
- Fiat quotes: `(ARS|AUD|BRL|CAD|CHF|EUR|GBP|...)/.*`
- Stablecoin pairs: `(FDUSD|BUSD|DAI|TUSD|USDC|USDP|USDT|...)/.*`
- No-leverage-tier crashers: `KAT|CHIP|BSB|OPG|BASED|ROBO|GENIUS|EDGE`

### Maintenance protocol

When Binance/Bybit launch new tokenized stocks or commodity pairs, they can enter the dynamic top-75 by volume before the regex catches them. Verify periodically:

```bash
# Over SSH tunnel: ssh -L 8092:127.0.0.1:8092 ubuntu@<vps>
curl -s -u <DASHBOARD_USER>:<DASHBOARD_PASS> http://127.0.0.1:8092/api/v1/whitelist
```

Confirmed incidents:
- **2026-05-06** — XAU (gold), INTC, CRCL snuck into live whitelist; regex extended.
- **2026-05-16** — Pairlist refresh exposed EDGE no-leverage-tier crash during backtest of partial May 2026; added to permanent exclusion.

---

## Development notes

### Editing the strategy

- **Never edit files in `NostalgiaForInfinity/`** — upstream repo, auto-updated by sidecar; edits will be overwritten.
- All local work lives in `user_data/strategies/`.
- Timeframe must always be `5m` (changing breaks all indicator calculations).
- After editing, smoke-test compile: `python3 -m py_compile user_data/strategies/NostalgiaScalpProX6X7Exp.py`.
- After deploying to VPS, verify health: container `Up`, strategy version in heartbeats, no real errors (ignore the known harmless `custom_stake_amount() got multiple values for argument 'pair'` TypeError — that's a pre-existing bug in `NostalgiaScalpProX6X7Opt`'s child-delegation, freqtrade just falls back to proposed_stake).

### Known issues

1. **`custom_stake_amount` TypeError noise** — when `NostalgiaScalpProX6X7Opt.custom_stake_amount` delegates to the child, freqtrade passes `pair` both positionally and via `**kwargs`, triggering `got multiple values for argument 'pair'`. Non-fatal (falls back to proposed_stake) but spams logs.
2. **First-cycle indicator compute warning** — `Strategy analysis took >75s` (25% of timeframe) on container startup; harmless, the multi-child wrapper is heavy on the first pass before the indicator cache warms up.

### Linting

```bash
black --line-length 119 user_data/strategies/
ruff check user_data/strategies/
```

### Testing

There are no project-specific unit tests; correctness is validated via the backtest suite. To run upstream NFI tests:

```bash
cd NostalgiaForInfinity
pytest tests/unit/ -v
```

---

## History

See `CLAUDE.md` for a detailed development timeline including the exp9 → exp10 → exp11 progression, the Apr 2024 pairlist deep-dive, and the multi-child architecture rationale.

---

**Strategy version**: `NostalgiaScalpProX6X7Opt 26.04.28.14.22`
**Last benchmark**: 2026-05-17 (6mo Dec 2025 – May 16 2026, Binance top-100; see [Backtest results](#backtest-results))
**Live deployment**: 4 Tencent VPS (all `NostalgiaScalpProX6X7Opt`, deployed 2026-05-17 07:44 GMT+8)
**Previous deployment** (for rollback): `NostalgiaScalpProX6X7Exp 26.05.16.exp11` (2026-05-16 → 2026-05-17)
