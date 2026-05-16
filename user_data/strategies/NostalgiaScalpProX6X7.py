"""
NostalgiaScalpProX6X7 — Best-of-breed scalp strategy with proper X6/X7 exit routing.

Each entry tag is prefixed to identify its parent strategy:
  x6_<tag>  → X6 entry logic → X6 custom_exit()
  x7_<tag>  → X7 entry logic → X7 custom_exit()

No mixing. X6 entries are exited by X6. X7 entries are exited by X7.

Active conditions:

  X6 child (tags 62, 143) — X6 implementations are provably safer than X7's:
    tag  62 : 27mo  98.0%  51T  worst -0.54%   (X7 impl worst: -99%)
    tag 143 : 27mo 100%    62T  worst  0%       (X7 impl worst: -73%)

  X7 child (all 12 ScalpPro conditions) — same set as NostalgiaScalpPro, routed to X7 exits:
    tag   4, 5, 42, 44, 45, 46, 61, 102, 104, 161, 162, 163

No DCA / grinding. Hard -10% stoploss. Long-only.

Architecture note:
  populate_indicators runs NostalgiaScalpProOptimized (~40% fewer indicator columns
  vs full X7; all columns needed by X6 conditions 62/143 and their exits are kept).
  populate_entry_trend runs both children on the enriched dataframe and
  filters each child's output to its allowed tag set before prefixing.
  All exit callbacks (_custom_exit, confirm_trade_exit, order_filled) strip
  the prefix and delegate to the originating child.
"""

import sys
import warnings
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from pandas import DataFrame, Series
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

sys.path.insert(0, str(Path(__file__).parent))

from NostalgiaForInfinityX6 import NostalgiaForInfinityX6
from NostalgiaScalpProOptimized import NostalgiaScalpProOptimized


# ---------------------------------------------------------------------------
# Allowed tag sets per child — tag filtering happens AFTER child entry trend
# so other conditions fire normally but get dropped before we use them.
# ---------------------------------------------------------------------------
_X6_TAGS: frozenset[str] = frozenset({"62", "143"})
_X7_TAGS: frozenset[str] = frozenset({"4", "5", "41", "42", "44", "45", "46", "61", "102", "104", "161", "162", "163"})

_PFX_X6 = "x6_"
_PFX_X7 = "x7_"


def _silence_futurewarnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message="Setting an item of incompatible dtype is deprecated*",
        category=FutureWarning,
    )


def _bool_signal(df: DataFrame, col: str) -> Series:
    """Convert mixed-type signal column (int / bool / str) to boolean Series."""
    if col not in df.columns:
        return Series(False, index=df.index)
    s = df[col]
    return (s == 1) | (s == True) | (s.astype(str).str.lower() == "true")  # noqa: E712


def _tag_allowed(tags: Series, allowed: frozenset[str]) -> Series:
    """
    True where every whitespace-separated token in the tag string is in `allowed`.
    Handles multi-token tags (e.g. "45 102 104" from simultaneous conditions).
    Empty / missing tags return False.
    """
    def _check(raw: str) -> bool:
        tokens = [t for t in raw.split() if t]
        return bool(tokens) and all(t in allowed for t in tokens)

    return tags.fillna("").astype(str).map(_check)


class NostalgiaScalpProX6X7(IStrategy):

    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False

    # Hard stoploss — each child's custom_exit still fires profit-take exits,
    # but the custom_stoploss from children is NOT used.
    stoploss = -0.10
    use_custom_stoploss = False
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    startup_candle_count = 800

    # No DCA / grinding / rebuy
    position_adjustment_enable = False

    # Dummy params so freqtrade doesn't complain about missing buy/sell params
    long_entry_signal_params: dict = {}
    short_entry_signal_params: dict = {}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._x6 = NostalgiaForInfinityX6(config)
        self._x7 = NostalgiaScalpProOptimized(config)
        # Restrict each child to only the conditions we use so populate_entry_trend
        # skips all other condition branches (lighter exec).
        self._x6.long_entry_signal_params = {
            "long_entry_condition_62_enable": True,
            "long_entry_condition_143_enable": True,
        }
        self._x7.long_entry_signal_params = {
            # All of ScalpPro's X7 conditions — same set, routed to X7 exits
            "long_entry_condition_4_enable": True,
            "long_entry_condition_5_enable": True,
            "long_entry_condition_41_enable": True,
            "long_entry_condition_42_enable": True,
            "long_entry_condition_44_enable": True,
            "long_entry_condition_45_enable": True,
            "long_entry_condition_46_enable": True,
            "long_entry_condition_61_enable": True,
            "long_entry_condition_102_enable": True,
            "long_entry_condition_104_enable": True,
            "long_entry_condition_161_enable": True,
            "long_entry_condition_162_enable": True,
            "long_entry_condition_163_enable": True,
        }
        self._x6.short_entry_signal_params = {}
        self._x7.short_entry_signal_params = {}
        # Mirror the wrapper's no-DCA / hard-stoploss settings so child
        # custom_exit() logic uses the same mode flags we intend.
        for child in (self._x6, self._x7):
            child.position_adjustment_enable = False
            child.use_custom_stoploss = False
            child.stoploss = -0.10

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync(self) -> None:
        """Propagate live freqtrade context to both child instances."""
        for child in (self._x6, self._x7):
            child.dp = self.dp
            if self.wallets:
                child.wallets = self.wallets
            child.config = self.config
            if "stake_currency" in self.config:
                child.stake_currency = self.config["stake_currency"]

    def _resolve(self, trade: Trade) -> Tuple[IStrategy, str]:
        """Return (child, original_tag) by inspecting the entry tag prefix."""
        tag = trade.enter_tag or ""
        if tag.startswith(_PFX_X6):
            return self._x6, tag[len(_PFX_X6):]
        if tag.startswith(_PFX_X7):
            return self._x7, tag[len(_PFX_X7):]
        # Fallback for trades opened before this wrapper (e.g. plain tag "45")
        return self._x7, tag

    @contextmanager
    def _patch_tags(self, trade: Optional[Trade] = None):
        """
        Strip prefixes from all open trades' enter_tag for the duration of a
        child callback, then restore them. Child strategies inspect other open
        trades' tags for grind/rebuy slot logic, so they must see clean tags.
        """
        patched: list[Tuple[Trade, str]] = []
        seen: set[int] = set()

        def _strip(t: Optional[Trade]) -> None:
            if t is None or id(t) in seen:
                return
            seen.add(id(t))
            orig = getattr(t, "enter_tag", None) or ""
            clean = (
                orig[len(_PFX_X6):] if orig.startswith(_PFX_X6)
                else orig[len(_PFX_X7):] if orig.startswith(_PFX_X7)
                else orig
            )
            if orig != clean:
                patched.append((t, orig))
                t.enter_tag = clean

        _strip(trade)
        for open_trade in Trade.get_trades_proxy(is_open=True):
            _strip(open_trade)

        try:
            yield
        finally:
            for t, orig in reversed(patched):
                t.enter_tag = orig

    # ------------------------------------------------------------------
    # Leverage & stake sizing — delegate to the child that owns the entry
    # ------------------------------------------------------------------

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        tag = entry_tag or ""
        child = self._x6 if tag.startswith(_PFX_X6) else self._x7
        clean = (
            tag[len(_PFX_X6):] if tag.startswith(_PFX_X6)
            else tag[len(_PFX_X7):] if tag.startswith(_PFX_X7)
            else tag
        )
        self._sync()
        if hasattr(child, "leverage"):
            return child.leverage(pair, current_time, current_rate, proposed_leverage, max_leverage, clean, side, **kwargs)
        return proposed_leverage

    def custom_stake_amount(
        self,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        tag = entry_tag or ""
        child = self._x6 if tag.startswith(_PFX_X6) else self._x7
        clean = (
            tag[len(_PFX_X6):] if tag.startswith(_PFX_X6)
            else tag[len(_PFX_X7):] if tag.startswith(_PFX_X7)
            else tag
        )
        self._sync()
        if hasattr(child, "custom_stake_amount"):
            return child.custom_stake_amount(current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, clean, side, **kwargs)
        return proposed_stake

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def bot_start(self, **kwargs) -> None:
        self._sync()
        for child in (self._x6, self._x7):
            if hasattr(child, "bot_start"):
                child.bot_start(**kwargs)

    def bot_loop_start(self, **kwargs) -> None:
        self._sync()
        for child in (self._x6, self._x7):
            if hasattr(child, "bot_loop_start"):
                child.bot_loop_start(**kwargs)

    # ------------------------------------------------------------------
    # Indicators & entry signals
    # ------------------------------------------------------------------

    def informative_pairs(self) -> List[Tuple]:
        self._sync()
        return list(set(self._x6.informative_pairs() + self._x7.informative_pairs()))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Run X7 indicators only — X7 is a strict superset of X6's indicator columns,
        so both children can run their entry_trend logic on this dataframe.
        """
        self._sync()
        return self._x7.populate_indicators(dataframe.copy(), metadata)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        with warnings.catch_warnings():
            _silence_futurewarnings()
            df_x6 = self._x6.populate_entry_trend(dataframe.copy(), metadata)
            df_x7 = self._x7.populate_entry_trend(dataframe.copy(), metadata)

        sig_x6 = _bool_signal(df_x6, "enter_long")
        tag_x6 = df_x6["enter_tag"].fillna("").astype(str).str.strip() if "enter_tag" in df_x6.columns else Series("", index=dataframe.index)

        sig_x7 = _bool_signal(df_x7, "enter_long")
        tag_x7 = df_x7["enter_tag"].fillna("").astype(str).str.strip() if "enter_tag" in df_x7.columns else Series("", index=dataframe.index)

        # Filter each child to its allowed tag set
        x6_fire = sig_x6 & _tag_allowed(tag_x6, _X6_TAGS)
        x7_fire = sig_x7 & _tag_allowed(tag_x7, _X7_TAGS)

        # Merge — apply X7 first, then X6 overwrites on conflict (X6 is more conservative)
        final_long = Series(False, index=dataframe.index)
        final_tag = Series("", index=dataframe.index)

        final_long.loc[x7_fire] = True
        final_tag.loc[x7_fire] = _PFX_X7 + tag_x7.loc[x7_fire]

        final_long.loc[x6_fire] = True
        final_tag.loc[x6_fire] = _PFX_X6 + tag_x6.loc[x6_fire]

        dataframe.loc[final_long, "enter_long"] = 1
        dataframe.loc[final_long, "enter_tag"] = final_tag.loc[final_long]

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    # ------------------------------------------------------------------
    # Exit routing — all callbacks strip prefix and delegate to child
    # ------------------------------------------------------------------

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        child, clean_tag = self._resolve(trade)
        with self._patch_tags(trade):
            trade.enter_tag = clean_tag
            return child.custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str,
        side: str,
        **kwargs,
    ) -> bool:
        tag = entry_tag or ""
        child = self._x6 if tag.startswith(_PFX_X6) else self._x7
        clean = (
            tag[len(_PFX_X6):] if tag.startswith(_PFX_X6)
            else tag[len(_PFX_X7):] if tag.startswith(_PFX_X7)
            else tag
        )
        self._sync()
        if hasattr(child, "confirm_trade_entry"):
            with self._patch_tags():
                return child.confirm_trade_entry(pair, order_type, amount, rate, time_in_force, current_time, clean, side, **kwargs)
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        child, clean_tag = self._resolve(trade)
        with self._patch_tags(trade):
            trade.enter_tag = clean_tag
            if hasattr(child, "confirm_trade_exit"):
                return child.confirm_trade_exit(pair, trade, order_type, amount, rate, time_in_force, exit_reason, current_time, **kwargs)
        return True

    def custom_entry_price(
        self,
        pair: str,
        trade: Optional[Trade],
        current_time: datetime,
        proposed_rate: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        tag = entry_tag or ""
        child = self._x6 if tag.startswith(_PFX_X6) else self._x7
        clean = (
            tag[len(_PFX_X6):] if tag.startswith(_PFX_X6)
            else tag[len(_PFX_X7):] if tag.startswith(_PFX_X7)
            else tag
        )
        self._sync()
        if hasattr(child, "custom_entry_price"):
            with self._patch_tags(trade):
                return child.custom_entry_price(pair, trade, current_time, proposed_rate, clean, side, **kwargs)
        return proposed_rate

    def order_filled(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> None:
        child, clean_tag = self._resolve(trade)
        with self._patch_tags(trade):
            trade.enter_tag = clean_tag
            if hasattr(child, "order_filled"):
                child.order_filled(pair, trade, order, current_time, **kwargs)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ):
        return None
