"""
Analyze per-entry-tag performance across all monthly backtest zips.
Usage: python3 user_data/scripts/analyze_tags.py --strategy NostalgiaForInfinityX6
Outputs: win rate, avg profit, avg duration, max loss, trade count per tag.
"""

import argparse
import json
import zipfile
from pathlib import Path
from collections import defaultdict
from datetime import timedelta

import pandas as pd


def load_trades_from_zips(strategy: str, results_dir: Path):
    all_trades = []
    zips = sorted(results_dir.glob(f"backtest_{strategy}_*.zip"))
    if not zips:
        print(f"No zip files found for strategy: {strategy}")
        return []
    for zpath in zips:
        month = zpath.stem.split("_")[-1]
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = [n for n in zf.namelist() if n.endswith(".json") and "meta" not in n]
                if not names:
                    continue
                with zf.open(names[0]) as f:
                    data = json.load(f)
                strategy_results = data.get("strategy", {})
                for strat_name, strat_data in strategy_results.items():
                    trades = strat_data.get("trades", [])
                    for t in trades:
                        t["_month"] = month
                    all_trades.extend(trades)
        except Exception as e:
            print(f"  Warning: could not read {zpath.name}: {e}")
    return all_trades


def parse_duration(s):
    if not s:
        return timedelta(0)
    try:
        # freqtrade format: "0:05:00" or "1 day, 2:30:00"
        if "day" in s:
            parts = s.split(", ")
            days = int(parts[0].split()[0])
            h, m, sec = map(int, parts[1].split(":"))
        else:
            days = 0
            h, m, sec = map(int, s.split(":"))
        return timedelta(days=days, hours=h, minutes=m, seconds=sec)
    except Exception:
        return timedelta(0)


def analyze(strategy: str, results_dir: Path, min_trades: int, min_winrate: float, max_avg_loss: float, max_duration_h: float):
    trades = load_trades_from_zips(strategy, results_dir)
    if not trades:
        return

    print(f"\nLoaded {len(trades)} trades for {strategy}\n")

    tag_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "profits": [], "durations": [], "losses_pct": []})

    for t in trades:
        tag = t.get("enter_tag", "unknown") or "unknown"
        # Normalize: strip strat prefix if present
        for prefix in ["STRAT_X6 ", "STRAT_X7 ", "STRAT_ "]:
            tag = tag.replace(prefix, "")
        tag = tag.strip()

        profit_pct = t.get("profit_abs", 0)
        profit_ratio = t.get("profit_ratio", 0) * 100  # to %

        dur_str = t.get("trade_duration", "") or ""
        # trade_duration may be seconds int or string
        if isinstance(dur_str, (int, float)):
            dur = timedelta(seconds=int(dur_str))
        else:
            dur = parse_duration(str(dur_str))

        if profit_ratio >= 0:
            tag_stats[tag]["wins"] += 1
        else:
            tag_stats[tag]["losses"] += 1
            tag_stats[tag]["losses_pct"].append(profit_ratio)

        tag_stats[tag]["profits"].append(profit_ratio)
        tag_stats[tag]["durations"].append(dur.total_seconds() / 3600)

    rows = []
    for tag, s in tag_stats.items():
        total = s["wins"] + s["losses"]
        if total < min_trades:
            continue
        win_pct = s["wins"] / total * 100
        avg_profit = sum(s["profits"]) / len(s["profits"])
        avg_dur_h = sum(s["durations"]) / len(s["durations"])
        max_loss = min(s["losses_pct"]) if s["losses_pct"] else 0.0
        rows.append({
            "tag": tag,
            "trades": total,
            "wins": s["wins"],
            "losses": s["losses"],
            "win_%": round(win_pct, 1),
            "avg_profit_%": round(avg_profit, 2),
            "avg_dur_h": round(avg_dur_h, 1),
            "worst_loss_%": round(max_loss, 2),
        })

    df = pd.DataFrame(rows).sort_values("win_%", ascending=False)

    print("=== All tags (min {} trades) ===".format(min_trades))
    print(df.to_string(index=False))

    # Filter: fast + high win rate + no big losses
    good = df[
        (df["win_%"] >= min_winrate)
        & (df["avg_dur_h"] <= max_duration_h)
        & (df["worst_loss_%"] >= max_avg_loss)
    ].copy()

    print(f"\n=== QUALIFYING tags (win≥{min_winrate}%, dur≤{max_duration_h}h, worst_loss≥{max_avg_loss}%) ===")
    if good.empty:
        print("  None found with current filters.")
    else:
        print(good.to_string(index=False))
        print(f"\nQualifying tags: {list(good['tag'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="NostalgiaForInfinityX6")
    ap.add_argument("--results-dir", default="user_data/backtest_results/monthly")
    ap.add_argument("--min-trades", type=int, default=3, help="Min trades to include a tag")
    ap.add_argument("--min-winrate", type=float, default=90.0)
    ap.add_argument("--max-duration-h", type=float, default=8.0, help="Max avg duration in hours")
    ap.add_argument("--max-avg-loss", type=float, default=-15.0, help="Worst single loss allowed (e.g. -15 means loss no worse than -15%%)")
    args = ap.parse_args()

    analyze(
        strategy=args.strategy,
        results_dir=Path(args.results_dir),
        min_trades=args.min_trades,
        min_winrate=args.min_winrate,
        max_duration_h=args.max_duration_h,
        max_avg_loss=args.max_avg_loss,
    )
