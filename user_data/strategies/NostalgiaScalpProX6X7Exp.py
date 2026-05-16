"""
NostalgiaScalpProX6X7Exp — Experimental fast scalp signals layered on X6X7Opt.

Extends NostalgiaScalpProX6X7Opt with tag 705a (MFI Volume Capitulation).
Uses only indicator columns already computed by NostalgiaScalpProOptimized.

  705a = base 705 + WILLR_14 < -80 + close >= open (green candle bounce confirmation)
  exp9: added close >= open filter — removes 9 of 10 historical red-body losses while keeping 95% WR

Risk management for exp_ trades:
  1. Progressive loss cut via custom_exit (evaluated every candle):
     10min/-5%, 15min/-3%, 30min/-2%, 60min/-1%, 120min/any loss
  2. Per-pair cooldown: after an exp_ loss, block re-entry for 4 hours
  3. Strategy-wide circuit breaker: after 2 exp_ losses within 1h, block all
     new exp_ entries (regime-detection — protects against correlated failures
     on new pairs / new market conditions).
  Winners resolve in <78 min avg; losers that don't bounce get cut early.

Risk management for non-exp (x6_/x7_) trades:
  X7.confirm_trade_exit (NostalgiaForInfinityX7.py:11598) denies stop_loss /
  trailing_stop_loss in both live AND backtest (only allows them on a true
  liquidation crossing), so the class-level stoploss = -0.10 in X6X7Opt never
  fires. We synthesise a backstop ladder in custom_exit (after X7's own exit
  logic gets first refusal):
     1h/-15%, 4h/-10%, 12h/-5%, 48h/any loss
  (We experimented with a 30min/-10% tier in exp10 — it capped worst-case
  losses by ~2pp but killed too many recoverable drawdowns, costing −33pp
  compounded over 6 months. Reverted; the strategy's edge depends on letting
  -10% dips ride.)

Backstop tiers from 1h onward apply to ALL trades (including exp_) — this
closes the rare gap where an exp_ trade survives past its 120min timeout
(only possible if profitable at 120min) and later turns red.

All experimental entries route to X7 custom_exit for profit-taking.
No DCA / grinding. Long-only.
"""

import numpy as np
from collections import deque
from datetime import datetime, timedelta
from pandas import DataFrame, Series
from freqtrade.persistence import Trade

from NostalgiaScalpProX6X7Opt import NostalgiaScalpProX6X7Opt

_PFX_EXP = "exp_"
_EXP_COOLDOWN_HOURS = 4
# Strategy-wide circuit breaker for exp_ trades
_EXP_CB_WINDOW_HOURS = 1
_EXP_CB_LOSS_THRESHOLD = 2


class NostalgiaScalpProX6X7Exp(NostalgiaScalpProX6X7Opt):
    def __init__(self, config=None) -> None:
        super().__init__(config)
        self._exp_last_loss: dict[str, datetime] = {}
        # Rolling timestamps of recent exp_ losses (oldest first)
        self._exp_recent_losses: deque = deque()

    @staticmethod
    def version() -> str:
        return "26.05.16.exp11"

    def _record_exp_loss(self, pair: str, current_time: datetime) -> None:
        self._exp_last_loss[pair] = current_time
        self._exp_recent_losses.append(current_time)

    def _exp_circuit_open(self, current_time: datetime) -> bool:
        cutoff = current_time - timedelta(hours=_EXP_CB_WINDOW_HOURS)
        while self._exp_recent_losses and self._exp_recent_losses[0] < cutoff:
            self._exp_recent_losses.popleft()
        return len(self._exp_recent_losses) >= _EXP_CB_LOSS_THRESHOLD

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        current_time: datetime,
        entry_tag: str,
        side: str,
        **kwargs,
    ) -> bool:
        if entry_tag and _PFX_EXP in entry_tag:
            last_loss = self._exp_last_loss.get(pair)
            if last_loss and (current_time - last_loss).total_seconds() < _EXP_COOLDOWN_HOURS * 3600:
                return False
            if self._exp_circuit_open(current_time):
                return False
        return True

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        tag = trade.enter_tag or ""
        is_exp = _PFX_EXP in tag
        trade_age_min = (current_time - trade.open_date_utc).total_seconds() / 60

        if is_exp:
            if trade_age_min >= 10 and current_profit < -0.05:
                self._record_exp_loss(pair, current_time)
                return "exp_cut_5pct"
            if trade_age_min >= 15 and current_profit < -0.03:
                self._record_exp_loss(pair, current_time)
                return "exp_cut_3pct"
            if trade_age_min >= 30 and current_profit < -0.02:
                self._record_exp_loss(pair, current_time)
                return "exp_cut_2pct"
            if trade_age_min >= 60 and current_profit < -0.01:
                self._record_exp_loss(pair, current_time)
                return "exp_cut_1pct"
            if trade_age_min >= 120 and current_profit < 0:
                self._record_exp_loss(pair, current_time)
                return "exp_timeout_exit"

        result = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if result is not None:
            return result

        # Backstop ladder — X7.confirm_trade_exit denies the class stoploss in
        # live AND backtest, so this is the only floor for non-exp losers.
        # Tiers from 1h+ apply to ALL trades (including exp_) so long-running
        # exp_ losers (alive past 120min then turning red) are also caught.
        if trade_age_min >= 60 and current_profit <= -0.15:
            return "backstop_1h_15pct"
        if trade_age_min >= 240 and current_profit <= -0.10:
            return "backstop_4h_10pct"
        if trade_age_min >= 720 and current_profit <= -0.05:
            return "backstop_12h_5pct"
        if trade_age_min >= 2880 and current_profit < 0:
            return "backstop_48h_timeout"

        return None

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)

        df = dataframe
        protections_ok = (df["num_empty_288"] <= 60) & (
            df.get("protections_long_global", Series(True, index=df.index)) == True  # noqa: E712
        )

        c705a = (
            (
                protections_ok
                & (df["RSI_3"] < 40)
                & (df["MFI_14_1h"] < 20)
                & (df["RSI_3_15m"] < 10)
                & (df["close"] < df["EMA_12"] * 0.950)
                & (df["AROONU_14"] < 25)
                & (df["STOCHRSIk_14_14_3_3_15m"] < 20)
                & (df["WILLR_14"] < -80)
                & (df["close"] > df["open"] * 1.01)
            )
            .fillna(False)
            .values
        )

        exp_tags = np.full(len(df), "", dtype=object)
        exp_tags[c705a] = "705a"

        existing_tags = dataframe["enter_tag"].fillna("").astype(str).values
        prefixed = np.where(exp_tags != "", _PFX_EXP + exp_tags, "")
        combined = np.where(
            (existing_tags != "") & (prefixed != ""),
            existing_tags + " " + prefixed,
            np.where(prefixed != "", prefixed, existing_tags),
        )

        dataframe.loc[c705a, "enter_long"] = 1
        dataframe["enter_tag"] = combined

        return dataframe

    def _resolve(self, trade: Trade):
        tag = trade.enter_tag or ""
        if _PFX_EXP in tag:
            parts = tag.split()
            for p in parts:
                if p.startswith(_PFX_EXP):
                    return self._x7, p[len(_PFX_EXP) :]
            return self._x7, tag
        return super()._resolve(trade)
