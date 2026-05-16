"""
NostalgiaScalpProX5X6X7 — Three-child scalp strategy with X5, X6, X7 exit routing.

Each entry tag is prefixed to identify its parent strategy:
  x5_<tag>  → X5 entry logic → X5 custom_exit()
  x6_<tag>  → X6 entry logic → X6 custom_exit()
  x7_<tag>  → X7 entry logic → X7 custom_exit()

No mixing. Each child's entries are exited by that same child.

Active conditions:

  X5 child (tag 41 only — Quick mode scalp, no DCA needed):
    tag  41    : 5yr 100%  33T  avg +7.93%  worst  0%     (Quick mode)

  X6 child (tags 62, 143) — X6 implementations are provably safer than X7's:
    tag  62   : 27mo  98.0%  51T  worst -0.54%   (X7 impl worst: -99%)
    tag 143   : 27mo 100%    62T  worst  0%       (X7 impl worst: -73%)

  X7 child (all 12 ScalpPro conditions) — same set as NostalgiaScalpPro, routed to X7 exits:
    tag   4, 5, 42, 44, 45, 46, 61, 102, 104, 161, 162, 163

No DCA / grinding. Hard -10% stoploss. Long-only.

Priority: X6 > X5 > X7 (X6 overwrites all, X5 overwrites X7).
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

from NostalgiaForInfinityX5 import NostalgiaForInfinityX5
from NostalgiaForInfinityX6 import NostalgiaForInfinityX6
from NostalgiaScalpProOptimized import NostalgiaScalpProOptimized


_X5_ALLOWED_EXACT: frozenset[str] = frozenset({"41"})
_X6_TAGS: frozenset[str] = frozenset({"62", "143"})
_X7_TAGS: frozenset[str] = frozenset({"4", "5", "42", "44", "45", "46", "61", "102", "104", "161", "162", "163"})

_PFX_X5 = "x5_"
_PFX_X6 = "x6_"
_PFX_X7 = "x7_"


def _silence_futurewarnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message="Setting an item of incompatible dtype is deprecated*",
        category=FutureWarning,
    )


def _bool_signal(df: DataFrame, col: str) -> Series:
    if col not in df.columns:
        return Series(False, index=df.index)
    s = df[col]
    return (s == 1) | (s == True) | (s.astype(str).str.lower() == "true")  # noqa: E712


def _tag_allowed(tags: Series, allowed: frozenset[str]) -> Series:
    def _check(raw: str) -> bool:
        tokens = [t for t in raw.split() if t]
        return bool(tokens) and all(t in allowed for t in tokens)

    return tags.fillna("").astype(str).map(_check)


def _x5_tag_allowed_exact(tags: Series, allowed: frozenset[str]) -> Series:
    return tags.fillna("").astype(str).str.strip().isin(allowed)


class NostalgiaScalpProX5X6X7(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False

    stoploss = -0.10
    use_custom_stoploss = False
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    startup_candle_count = 800

    position_adjustment_enable = False

    long_entry_signal_params: dict = {}
    short_entry_signal_params: dict = {}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._x5 = NostalgiaForInfinityX5(config)
        self._x6 = NostalgiaForInfinityX6(config)
        self._x7 = NostalgiaScalpProOptimized(config)
        self._ind_cache: dict[str, dict[str, DataFrame]] = {}

        self._x5.long_entry_signal_params = {
            "long_entry_condition_41_enable": True,
        }
        self._x6.long_entry_signal_params = {
            "long_entry_condition_62_enable": True,
            "long_entry_condition_143_enable": True,
        }
        self._x7.long_entry_signal_params = {
            "long_entry_condition_4_enable": True,
            "long_entry_condition_5_enable": True,
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
        self._x5.short_entry_signal_params = {}
        self._x6.short_entry_signal_params = {}
        self._x7.short_entry_signal_params = {}

        for child in (self._x5, self._x6, self._x7):
            child.position_adjustment_enable = False
            child.use_custom_stoploss = False
            child.stoploss = -0.10

    def _sync(self) -> None:
        for child in (self._x5, self._x6, self._x7):
            child.dp = self.dp
            if self.wallets:
                child.wallets = self.wallets
            child.config = self.config
            if "stake_currency" in self.config:
                child.stake_currency = self.config["stake_currency"]

    def _resolve(self, trade: Trade) -> Tuple[IStrategy, str]:
        tag = trade.enter_tag or ""
        if tag.startswith(_PFX_X5):
            return self._x5, tag[len(_PFX_X5) :]
        if tag.startswith(_PFX_X6):
            return self._x6, tag[len(_PFX_X6) :]
        if tag.startswith(_PFX_X7):
            return self._x7, tag[len(_PFX_X7) :]
        return self._x7, tag

    @contextmanager
    def _patch_tags(self, trade: Optional[Trade] = None):
        patched: list[Tuple[Trade, str]] = []
        seen: set[int] = set()

        def _strip(t: Optional[Trade]) -> None:
            if t is None or id(t) in seen:
                return
            seen.add(id(t))
            orig = getattr(t, "enter_tag", None) or ""
            clean = (
                orig[len(_PFX_X5) :]
                if orig.startswith(_PFX_X5)
                else orig[len(_PFX_X6) :]
                if orig.startswith(_PFX_X6)
                else orig[len(_PFX_X7) :]
                if orig.startswith(_PFX_X7)
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

    def _child_for_tag(self, entry_tag: str) -> IStrategy:
        tag = entry_tag or ""
        if tag.startswith(_PFX_X5):
            return self._x5
        if tag.startswith(_PFX_X6):
            return self._x6
        return self._x7

    def _clean_tag(self, entry_tag: str) -> str:
        tag = entry_tag or ""
        for pfx in (_PFX_X5, _PFX_X6, _PFX_X7):
            if tag.startswith(pfx):
                return tag[len(pfx) :]
        return tag

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
        child = self._child_for_tag(tag)
        clean = self._clean_tag(tag)
        self._sync()
        if hasattr(child, "leverage"):
            return child.leverage(
                pair, current_time, current_rate, proposed_leverage, max_leverage, clean, side, **kwargs
            )
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
        child = self._child_for_tag(tag)
        clean = self._clean_tag(tag)
        self._sync()
        if hasattr(child, "custom_stake_amount"):
            return child.custom_stake_amount(
                current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, clean, side, **kwargs
            )
        return proposed_stake

    def bot_start(self, **kwargs) -> None:
        self._sync()
        for child in (self._x5, self._x6, self._x7):
            if hasattr(child, "bot_start"):
                child.bot_start(**kwargs)

    def bot_loop_start(self, **kwargs) -> None:
        self._sync()
        for child in (self._x5, self._x6, self._x7):
            if hasattr(child, "bot_loop_start"):
                child.bot_loop_start(**kwargs)

    def informative_pairs(self) -> List[Tuple]:
        self._sync()
        pairs = set()
        for child in (self._x5, self._x6, self._x7):
            pairs.update(child.informative_pairs())
        return list(pairs)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        pair = metadata.get("pair", "")
        df_x5 = self._x5.populate_indicators(dataframe.copy(), metadata)
        df_x7 = self._x7.populate_indicators(dataframe.copy(), metadata)
        self._ind_cache[pair] = {"x5": df_x5, "x7": df_x7}
        return df_x7

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync()
        pair = metadata.get("pair", "")
        cached = self._ind_cache.get(pair, {})
        df_x5_src = cached.get("x5", dataframe)
        df_x7_src = cached.get("x7", dataframe)

        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        with warnings.catch_warnings():
            _silence_futurewarnings()
            df_x5 = self._x5.populate_entry_trend(df_x5_src.copy(), metadata)
            df_x6 = self._x6.populate_entry_trend(dataframe.copy(), metadata)
            df_x7 = self._x7.populate_entry_trend(df_x7_src.copy(), metadata)

        sig_x5 = _bool_signal(df_x5, "enter_long")
        tag_x5 = (
            df_x5["enter_tag"].fillna("").astype(str).str.strip()
            if "enter_tag" in df_x5.columns
            else Series("", index=dataframe.index)
        )

        sig_x6 = _bool_signal(df_x6, "enter_long")
        tag_x6 = (
            df_x6["enter_tag"].fillna("").astype(str).str.strip()
            if "enter_tag" in df_x6.columns
            else Series("", index=dataframe.index)
        )

        sig_x7 = _bool_signal(df_x7, "enter_long")
        tag_x7 = (
            df_x7["enter_tag"].fillna("").astype(str).str.strip()
            if "enter_tag" in df_x7.columns
            else Series("", index=dataframe.index)
        )

        x5_fire = sig_x5 & _x5_tag_allowed_exact(tag_x5, _X5_ALLOWED_EXACT)
        x6_fire = sig_x6 & _tag_allowed(tag_x6, _X6_TAGS)
        x7_fire = sig_x7 & _tag_allowed(tag_x7, _X7_TAGS)

        final_long = Series(False, index=dataframe.index)
        final_tag = Series("", index=dataframe.index)

        final_long.loc[x7_fire] = True
        final_tag.loc[x7_fire] = _PFX_X7 + tag_x7.loc[x7_fire]

        final_long.loc[x5_fire] = True
        final_tag.loc[x5_fire] = _PFX_X5 + tag_x5.loc[x5_fire]

        final_long.loc[x6_fire] = True
        final_tag.loc[x6_fire] = _PFX_X6 + tag_x6.loc[x6_fire]

        dataframe.loc[final_long, "enter_long"] = 1
        dataframe.loc[final_long, "enter_tag"] = final_tag.loc[final_long]

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

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
        child = self._child_for_tag(tag)
        clean = self._clean_tag(tag)
        self._sync()
        if hasattr(child, "confirm_trade_entry"):
            with self._patch_tags():
                return child.confirm_trade_entry(
                    pair, order_type, amount, rate, time_in_force, current_time, clean, side, **kwargs
                )
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
                return child.confirm_trade_exit(
                    pair, trade, order_type, amount, rate, time_in_force, exit_reason, current_time, **kwargs
                )
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
        child = self._child_for_tag(tag)
        clean = self._clean_tag(tag)
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
