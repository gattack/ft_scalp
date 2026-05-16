#!/usr/bin/env python3
"""
Summarize monthly backtest results from user_data/backtest_results/monthly/.
Usage: python user_data/scripts/summarize_monthly.py [--strategy NostalgiaForInfinityX7]
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


def load_backtest_result(path: Path) -> dict | None:
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                json_names = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n and "_market" not in n]
                if not json_names:
                    print(f"[WARN] No result JSON in {path.name}")
                    return None
                with z.open(json_names[0]) as f:
                    data = json.load(f)
        else:
            with open(path) as f:
                data = json.load(f)
    except Exception as e:
        print(f"[WARN] Cannot read {path.name}: {e}")
        return None

    strategy_results = data.get("strategy", {})
    if not strategy_results:
        print(f"[WARN] No strategy key in {path.name}")
        return None

    strat_name = next(iter(strategy_results))
    s = strategy_results[strat_name]

    parts = path.stem.split("_")
    month_label = parts[-1] if parts[-1].isdigit() and len(parts[-1]) == 6 else path.stem

    total_trades = s.get("total_trades", 0)
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    draws = s.get("draws", 0)
    win_rate = (wins / total_trades * 100) if total_trades else 0

    # profit_total and profit_mean are ratios (0.08 = 8%), convert to %
    profit_total_pct = s.get("profit_total", None)
    if profit_total_pct is not None:
        profit_total_pct = profit_total_pct * 100

    avg_profit_pct = s.get("profit_mean", None)
    if avg_profit_pct is not None:
        avg_profit_pct = avg_profit_pct * 100

    max_drawdown = s.get("max_drawdown_account", s.get("max_drawdown", None))
    if max_drawdown is not None and abs(max_drawdown) < 1:
        max_drawdown *= 100

    holding_avg = s.get("holding_avg", "")

    return {
        "month": month_label,
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_%": round(win_rate, 1),
        "profit_total_%": round(profit_total_pct, 2) if profit_total_pct is not None else "N/A",
        "avg_profit_%": round(avg_profit_pct, 3) if avg_profit_pct is not None else "N/A",
        "max_dd_%": round(max_drawdown, 2) if max_drawdown is not None else "N/A",
        "avg_duration": str(holding_avg),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="NostalgiaForInfinityX7")
    parser.add_argument("--results-dir", default="user_data/backtest_results/monthly")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Results dir not found: {results_dir}")
        sys.exit(1)

    files = sorted(results_dir.glob(f"backtest_{args.strategy}_*.zip"))
    if not files:
        files = sorted(results_dir.glob(f"backtest_{args.strategy}_*.json"))
    if not files:
        print(f"No result files for strategy '{args.strategy}' in {results_dir}")
        sys.exit(1)

    rows = [r for f in files if (r := load_backtest_result(f)) is not None]
    if not rows:
        print("No valid results loaded.")
        sys.exit(1)

    print(f"\n=== Monthly Backtest Summary: {args.strategy} ===\n")

    if HAS_TABULATE:
        print(tabulate(rows, headers="keys", tablefmt="github", floatfmt=".2f"))
    else:
        headers = list(rows[0].keys())
        print(",".join(headers))
        for r in rows:
            print(",".join(str(r[h]) for h in headers))

    numeric = [r for r in rows if isinstance(r["trades"], int) and r["trades"] > 0]
    if numeric:
        total_trades = sum(r["trades"] for r in numeric)
        total_wins = sum(r["wins"] for r in numeric)
        total_losses = sum(r["losses"] for r in numeric)
        overall_wr = total_wins / total_trades * 100 if total_trades else 0
        profit_vals = [r["profit_total_%"] for r in numeric if isinstance(r["profit_total_%"], float)]
        dd_vals = [r["max_dd_%"] for r in numeric if isinstance(r["max_dd_%"], float)]

        print(f"\n--- Aggregate ({len(numeric)} months) ---")
        print(f"Total trades  : {total_trades}")
        print(f"Wins/Losses   : {total_wins}/{total_losses}")
        print(f"Overall win % : {overall_wr:.1f}%")
        if profit_vals:
            compound = 1.0
            for r in profit_vals:
                compound *= (1 + r / 100)
            compound_pct = (compound - 1) * 100
            print(f"Sum profit %  : {sum(profit_vals):.2f}%  (simple, non-compounded)")
            print(f"Compounded %  : {compound_pct:.2f}%  (unlimited stake run in sequence)")
            print(f"  e.g. $10k → ${10000 * compound:,.0f}")
            print(f"Avg monthly % : {sum(profit_vals)/len(profit_vals):.2f}%")
            print(f"Best month    : {max(profit_vals):.2f}%")
            print(f"Worst month   : {min(profit_vals):.2f}%")
        if dd_vals:
            print(f"Avg max DD %  : {sum(dd_vals)/len(dd_vals):.2f}%")
            print(f"Worst DD %    : {max(dd_vals):.2f}%")
    print()


if __name__ == "__main__":
    main()
