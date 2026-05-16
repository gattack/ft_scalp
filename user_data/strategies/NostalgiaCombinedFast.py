import logging
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple
import types

import numpy as np
import pandas as pd
from pandas import DataFrame, Series
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
import talib.abstract as ta

# ---------------------------------------------------------------------------------------
# NostalgiaForInfinityX6.py and NostalgiaForInfinityX7.py must be in the same folder.
# ---------------------------------------------------------------------------------------
from NostalgiaForInfinityX6 import NostalgiaForInfinityX6
from NostalgiaForInfinityX7 import NostalgiaForInfinityX7

log = logging.getLogger(__name__)


def _silence_nfi_futurewarnings():
    warnings.filterwarnings(
        "ignore",
        message="Setting an item of incompatible dtype is deprecated*",
        category=FutureWarning,
    )

class NostalgiaCombinedFast(IStrategy):
    """
    [Final Version] Global Whitelist + X6 Priority
    - Entry: Allowed if the tag is in the analyzed whitelist, regardless of the time of day.
    - Priority: If X6 and X7 signal simultaneously, the aggressive X6 leads (to maximize profit).
    """
    
    INTERFACE_VERSION = 3 
    timeframe = "5m"
    can_short = True
    
    # ROI/Stoploss are fully delegated to the child strategy's custom_exit
    stoploss = -0.99 
    minimal_roi = {"0": 100} 
    
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True

    position_adjustment_enable = True
    max_entry_position_adjustment = -1
    
    # Ensure sufficient data
    startup_candle_count = 800
    _signal_db_ready = False
    _signal_last_logged_ts: dict[str, pd.Timestamp]
    _signal_features: list[str] = [
        "ai_rsi_14",
        "ai_adx_14",
        "ai_atr_pct",
        "ai_ema_gap",
        "ai_bb_width",
        "ai_bb_pos",
        "ai_ret_1",
        "ai_ret_3",
        "ai_ret_12",
        "ai_range_pct",
        "ai_vol_z",
        "ai_hour",
        "ai_dow",
    ]

    def _clean_prefixed_tag(self, tag: str | None) -> str | None:
        if not tag:
            return None
        cleaned = (
            tag.replace("STRAT_X6_OR ", "")
            .replace("STRAT_X6_AND ", "")
            .replace("STRAT_X7_OR ", "")
            .replace("STRAT_X7_AND ", "")
            .strip()
        )
        return cleaned or None

    def _signal_mask(self, df: DataFrame, col: str) -> Series:
        """
        Convert mixed signal columns (int/bool/str) from child strategies to a stable boolean mask.
        """
        if col not in df.columns:
            return Series(False, index=df.index)
        s = df[col]
        # Child strategies sometimes use "" / 0 / 1 / bool for signal columns.
        return (s == 1) | (s == True) | (s.astype(str).str.lower() == "true")

    @staticmethod
    def _tag_tokens(tag: str | None) -> tuple[str, ...]:
        if not tag:
            return tuple()
        return tuple(part for part in str(tag).strip().split() if part)

    def _tag_matches_whitelist(self, tags: pd.Series, allowed_tokens: set[str]) -> pd.Series:
        """
        Child NFI logic evaluates tags token-by-token via ``entry_tag.split()``.
        Wrapper filtering must use the same semantics instead of exact-string equality.
        """
        if tags.empty:
            return Series(False, index=tags.index)
        allowed = {str(x).strip() for x in allowed_tokens if str(x).strip()}
        return tags.fillna("").astype(str).map(
            lambda raw: bool(self._tag_tokens(raw)) and all(token in allowed for token in self._tag_tokens(raw))
        )

    def _signal_cfg(self) -> dict:
        return self.config.get("signal_learning", {}) if self.config else {}

    def _signal_learning_enabled(self) -> bool:
        return bool(self._signal_cfg().get("enabled", False))

    def _signal_db_path(self) -> Path:
        cfg = self._signal_cfg()
        db_path = str(cfg.get("db_path", "user_data/models/nfi_signal_meta/signals.sqlite"))
        if db_path.startswith("sqlite:///"):
            db_path = db_path[len("sqlite:///") :]
        return Path(db_path)

    def _signal_bootstrap_lookback(self) -> int:
        return int(self._signal_cfg().get("bootstrap_lookback_candles", 0) or 0)

    def _signal_bootstrap_stale_hours(self) -> float:
        return float(self._signal_cfg().get("bootstrap_if_stale_hours", 0) or 0)

    def _ensure_signal_db(self) -> None:
        if self._signal_db_ready or not self._signal_learning_enabled():
            return

        db_path = self._signal_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candle_ts TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    raw_signal INTEGER NOT NULL,
                    safe_signal INTEGER NOT NULL,
                    final_entry INTEGER NOT NULL,
                    final_tag TEXT,
                    close REAL,
                    ai_rsi_14 REAL,
                    ai_adx_14 REAL,
                    ai_atr_pct REAL,
                    ai_ema_gap REAL,
                    ai_bb_width REAL,
                    ai_bb_pos REAL,
                    ai_ret_1 REAL,
                    ai_ret_3 REAL,
                    ai_ret_12 REAL,
                    ai_range_pct REAL,
                    ai_vol_z REAL,
                    ai_hour REAL,
                    ai_dow REAL,
                    label_horizon_candles INTEGER,
                    label_return REAL,
                    label_mfe REAL,
                    label_mae REAL,
                    label INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(candle_ts, pair, side, source, tag)
                )
                """
            )
            conn.commit()
            self._signal_db_ready = True
        finally:
            conn.close()

    def _get_last_logged_ts(self, key: str, pair: str, sources: list[str]) -> pd.Timestamp | None:
        cached = self._signal_last_logged_ts.get(key, None)
        if cached is not None:
            return cached

        self._ensure_signal_db()
        if not self._signal_db_ready or not sources:
            return None

        placeholders = ", ".join("?" for _ in sources)
        query = (
            f"SELECT MAX(candle_ts) FROM signal_events "
            f"WHERE pair = ? AND source IN ({placeholders})"
        )
        conn = sqlite3.connect(self._signal_db_path(), timeout=30)
        try:
            row = conn.execute(query, [pair, *sources]).fetchone()
        finally:
            conn.close()

        last_value = row[0] if row else None
        if not last_value:
            return None

        ts = pd.to_datetime(last_value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        self._signal_last_logged_ts[key] = ts
        return ts

    @staticmethod
    def _safe_series(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
        return pd.Series(default, index=df.index, dtype=float)

    def _populate_signal_features(self, df: pd.DataFrame) -> DataFrame:
        close = self._safe_series(df, "close")
        high = self._safe_series(df, "high")
        low = self._safe_series(df, "low")
        vol = self._safe_series(df, "volume")

        df["ai_rsi_14"] = ta.RSI(df, timeperiod=14)
        df["ai_adx_14"] = ta.ADX(df, timeperiod=14)
        atr = ta.ATR(df, timeperiod=14)
        df["ai_atr_pct"] = atr / close.replace(0, np.nan)

        ema20 = ta.EMA(df, timeperiod=20)
        ema50 = ta.EMA(df, timeperiod=50)
        df["ai_ema_gap"] = (ema20 - ema50) / close.replace(0, np.nan)

        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        up = mid + 2.0 * std
        lo = mid - 2.0 * std
        bb_span = (up - lo).replace(0, np.nan)
        df["ai_bb_width"] = (up - lo) / mid.replace(0, np.nan)
        df["ai_bb_pos"] = (close - lo) / bb_span

        df["ai_ret_1"] = close.pct_change(1)
        df["ai_ret_3"] = close.pct_change(3)
        df["ai_ret_12"] = close.pct_change(12)
        df["ai_range_pct"] = (high - low) / close.replace(0, np.nan)

        vmean = vol.rolling(20).mean()
        vstd = vol.rolling(20).std().replace(0, np.nan)
        df["ai_vol_z"] = (vol - vmean) / vstd

        if "date" in df.columns:
            dts = pd.to_datetime(df["date"], utc=True, errors="coerce")
            df["ai_hour"] = dts.dt.hour.astype(float)
            df["ai_dow"] = dts.dt.dayofweek.astype(float)
        else:
            df["ai_hour"] = np.nan
            df["ai_dow"] = np.nan

        return df

    def _prepare_signal_window(
        self,
        key: str,
        pair: str,
        work: DataFrame,
        sources: list[str],
    ) -> DataFrame:
        if work.empty:
            return work

        last_logged = self._get_last_logged_ts(key, pair, sources)
        latest_date = work["date"].max()
        bootstrap_lookback = self._signal_bootstrap_lookback()
        stale_hours = self._signal_bootstrap_stale_hours()

        should_bootstrap = False
        if last_logged is None:
            should_bootstrap = bootstrap_lookback > 0
        elif stale_hours > 0:
            age_hours = (latest_date - last_logged).total_seconds() / 3600.0
            should_bootstrap = age_hours >= stale_hours and bootstrap_lookback > 0

        if should_bootstrap:
            return work.tail(bootstrap_lookback).copy()

        if last_logged is None:
            self._signal_last_logged_ts[key] = latest_date
            return work.iloc[0:0].copy()

        return work.loc[work["date"] > last_logged].copy()

    def _log_signal_candidates(
        self,
        metadata: dict,
        df: DataFrame,
        s_x7: Series,
        t_x7: Series,
        s_x6: Series,
        t_x6: Series,
        s_short_x7: Series,
        t_short_x7: Series,
        s_short_x6: Series,
        t_short_x6: Series,
        is_x7_safe: Series,
        is_x6_safe: Series,
        is_short_x7_safe: Series,
        is_short_x6_safe: Series,
        final_long_entry: Series,
        final_short_entry: Series,
        final_tags: Series,
        extra_long_x7: Series | None = None,
        extra_long_x6: Series | None = None,
        extra_short_x7: Series | None = None,
        extra_short_x6: Series | None = None,
    ) -> None:
        if not self._signal_learning_enabled() or df.empty:
            return

        self._ensure_signal_db()
        pair = str(metadata.get("pair", "UNKNOWN"))
        label_horizon = int(self._signal_cfg().get("label_horizon_candles", 24))
        key = f"self_exec|{pair}"

        work = df.copy()
        if "date" not in work.columns:
            return
        work["date"] = pd.to_datetime(work["date"], utc=True, errors="coerce")
        work = work.dropna(subset=["date"])
        work = self._prepare_signal_window(
            key,
            pair,
            work,
            ["x7", "x6", "x7_raw", "x6_raw"],
        )
        if work.empty:
            return

        candidates = []

        def add_candidate(
            row_data,
            side: str,
            source: str,
            tag_value,
            raw_mask: bool,
            safe_mask: bool,
            final_mask: bool,
            raw_only: bool = False,
        ):
            tag_clean = str(tag_value).strip()
            if not raw_mask or not tag_clean:
                return
            source_name = source if not raw_only else f"{source}_raw"
            final_tag = str(row_data.get("enter_tag", "") or "")
            payload = {
                "candle_ts": row_data["date"].isoformat(),
                "pair": pair,
                "side": side,
                "source": source_name,
                "tag": tag_clean,
                "raw_signal": 1,
                "safe_signal": int(bool(safe_mask)),
                "final_entry": int(bool(final_mask)),
                "final_tag": final_tag if final_mask else "",
                "close": float(row_data.get("close", np.nan)),
                "label_horizon_candles": label_horizon,
            }
            if raw_only:
                payload["safe_signal"] = 0
                payload["final_entry"] = 0
                payload["final_tag"] = ""
            for feature in self._signal_features:
                value = row_data.get(feature, np.nan)
                try:
                    payload[feature] = float(value)
                except Exception:
                    payload[feature] = np.nan
            candidates.append(payload)

        for idx in work.index:
            row = work.loc[idx]
            final_long = bool(final_long_entry.loc[idx])
            final_short = bool(final_short_entry.loc[idx])
            final_tag = str(final_tags.loc[idx] or "")

            add_candidate(
                row, "long", "x7", t_x7.loc[idx], bool(s_x7.loc[idx]), bool(is_x7_safe.loc[idx]),
                final_long and final_tag.startswith("STRAT_X7")
            )
            add_candidate(
                row, "long", "x6", t_x6.loc[idx], bool(s_x6.loc[idx]), bool(is_x6_safe.loc[idx]),
                final_long and final_tag.startswith("STRAT_X6")
            )
            add_candidate(
                row, "short", "x7", t_short_x7.loc[idx], bool(s_short_x7.loc[idx]), bool(is_short_x7_safe.loc[idx]),
                final_short and final_tag.startswith("STRAT_X7")
            )
            add_candidate(
                row, "short", "x6", t_short_x6.loc[idx], bool(s_short_x6.loc[idx]), bool(is_short_x6_safe.loc[idx]),
                final_short and final_tag.startswith("STRAT_X6")
            )

            if extra_long_x7 is not None:
                add_candidate(row, "long", "x7", t_x7.loc[idx], bool(extra_long_x7.loc[idx]), False, False, raw_only=True)
            if extra_long_x6 is not None:
                add_candidate(row, "long", "x6", t_x6.loc[idx], bool(extra_long_x6.loc[idx]), False, False, raw_only=True)
            if extra_short_x7 is not None:
                add_candidate(row, "short", "x7", t_short_x7.loc[idx], bool(extra_short_x7.loc[idx]), False, False, raw_only=True)
            if extra_short_x6 is not None:
                add_candidate(row, "short", "x6", t_short_x6.loc[idx], bool(extra_short_x6.loc[idx]), False, False, raw_only=True)

        if not candidates:
            self._signal_last_logged_ts[key] = work["date"].max()
            return

        conn = sqlite3.connect(self._signal_db_path(), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executemany(
                """
                INSERT OR REPLACE INTO signal_events (
                    candle_ts, pair, side, source, tag, raw_signal, safe_signal, final_entry, final_tag, close,
                    ai_rsi_14, ai_adx_14, ai_atr_pct, ai_ema_gap, ai_bb_width, ai_bb_pos,
                    ai_ret_1, ai_ret_3, ai_ret_12, ai_range_pct, ai_vol_z, ai_hour, ai_dow,
                    label_horizon_candles
                ) VALUES (
                    :candle_ts, :pair, :side, :source, :tag, :raw_signal, :safe_signal, :final_entry, :final_tag, :close,
                    :ai_rsi_14, :ai_adx_14, :ai_atr_pct, :ai_ema_gap, :ai_bb_width, :ai_bb_pos,
                    :ai_ret_1, :ai_ret_3, :ai_ret_12, :ai_range_pct, :ai_vol_z, :ai_hour, :ai_dow,
                    :label_horizon_candles
                )
                """,
                candidates,
            )
            conn.commit()
        finally:
            conn.close()
        self._signal_last_logged_ts[key] = work["date"].max()

    def _log_external_signal_rows(self, metadata: dict, df: DataFrame, source_label: str) -> None:
        if not self._signal_learning_enabled() or df.empty:
            return

        self._ensure_signal_db()
        pair = str(metadata.get("pair", "UNKNOWN"))
        label_horizon = int(self._signal_cfg().get("label_horizon_candles", 24))
        key = f"{source_label}|{pair}"
        last_logged = self._get_last_logged_ts(key, pair, [source_label])

        work = df.copy()
        if "date" not in work.columns:
            return
        work["date"] = pd.to_datetime(work["date"], utc=True, errors="coerce")
        work = work.dropna(subset=["date"])
        work = self._prepare_signal_window(key, pair, work, [source_label])
        if work.empty:
            return

        candidates = []

        def add(row_data, side: str, enter_value, tag_value):
            if int(enter_value or 0) != 1:
                return
            tag_clean = str(tag_value or "").strip()
            if not tag_clean:
                return
            payload = {
                "candle_ts": row_data["date"].isoformat(),
                "pair": pair,
                "side": side,
                "source": source_label,
                "tag": tag_clean,
                "raw_signal": 1,
                "safe_signal": 1,
                "final_entry": 1,
                "final_tag": tag_clean,
                "close": float(row_data.get("close", np.nan)),
                "label_horizon_candles": label_horizon,
            }
            for feature in self._signal_features:
                value = row_data.get(feature, np.nan)
                try:
                    payload[feature] = float(value)
                except Exception:
                    payload[feature] = np.nan
            candidates.append(payload)

        for _, row in work.iterrows():
            add(row, "long", row.get("enter_long", 0), row.get("enter_tag", ""))
            add(row, "short", row.get("enter_short", 0), row.get("enter_tag", ""))

        if not candidates:
            self._signal_last_logged_ts[key] = work["date"].max()
            return

        conn = sqlite3.connect(self._signal_db_path(), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executemany(
                """
                INSERT OR REPLACE INTO signal_events (
                    candle_ts, pair, side, source, tag, raw_signal, safe_signal, final_entry, final_tag, close,
                    ai_rsi_14, ai_adx_14, ai_atr_pct, ai_ema_gap, ai_bb_width, ai_bb_pos,
                    ai_ret_1, ai_ret_3, ai_ret_12, ai_range_pct, ai_vol_z, ai_hour, ai_dow,
                    label_horizon_candles
                ) VALUES (
                    :candle_ts, :pair, :side, :source, :tag, :raw_signal, :safe_signal, :final_entry, :final_tag, :close,
                    :ai_rsi_14, :ai_adx_14, :ai_atr_pct, :ai_ema_gap, :ai_bb_width, :ai_bb_pos,
                    :ai_ret_1, :ai_ret_3, :ai_ret_12, :ai_range_pct, :ai_vol_z, :ai_hour, :ai_dow,
                    :label_horizon_candles
                )
                """,
                candidates,
            )
            conn.commit()
        finally:
            conn.close()
        self._signal_last_logged_ts[key] = work["date"].max()

    def _log_raw_signal_stream(
        self,
        metadata: dict,
        df_x7: DataFrame,
        df_x6: DataFrame,
        source_prefix: str,
    ) -> None:
        if not self._signal_learning_enabled() or df_x7.empty or df_x6.empty:
            return

        self._ensure_signal_db()
        pair = str(metadata.get("pair", "UNKNOWN"))
        label_horizon = int(self._signal_cfg().get("label_horizon_candles", 24))
        key = f"{source_prefix}|{pair}"
        last_logged = self._get_last_logged_ts(
            key,
            pair,
            [f"{source_prefix}_x7_raw", f"{source_prefix}_x6_raw"],
        )

        work = df_x7[["date"]].copy() if "date" in df_x7.columns else pd.DataFrame()
        if work.empty:
            return
        work["date"] = pd.to_datetime(work["date"], utc=True, errors="coerce")
        work = work.dropna(subset=["date"])
        work = self._prepare_signal_window(
            key,
            pair,
            work,
            [f"{source_prefix}_x7_raw", f"{source_prefix}_x6_raw"],
        )
        if work.empty:
            return

        s_x7_long = self._signal_mask(df_x7, "enter_long")
        s_x6_long = self._signal_mask(df_x6, "enter_long")
        s_x7_short = self._signal_mask(df_x7, "enter_short")
        s_x6_short = self._signal_mask(df_x6, "enter_short")

        t_x7 = df_x7["enter_tag"].fillna("") if "enter_tag" in df_x7.columns else pd.Series("", index=df_x7.index)
        t_x6 = df_x6["enter_tag"].fillna("") if "enter_tag" in df_x6.columns else pd.Series("", index=df_x6.index)
        close_series = (
            pd.to_numeric(df_x7["close"], errors="coerce")
            if "close" in df_x7.columns
            else pd.Series(np.nan, index=df_x7.index)
        )

        candidates = []

        def add(idx, side: str, source: str, tag_value):
            tag_clean = str(tag_value or "").strip()
            if not tag_clean:
                return
            row = df_x7.loc[idx]
            payload = {
                "candle_ts": pd.to_datetime(row.get("date"), utc=True, errors="coerce").isoformat(),
                "pair": pair,
                "side": side,
                "source": source,
                "tag": tag_clean,
                "raw_signal": 1,
                "safe_signal": 0,
                "final_entry": 0,
                "final_tag": "",
                "close": float(close_series.loc[idx]) if idx in close_series.index else np.nan,
                "label_horizon_candles": label_horizon,
            }
            for feature in self._signal_features:
                value = row.get(feature, np.nan)
                try:
                    payload[feature] = float(value)
                except Exception:
                    payload[feature] = np.nan
            candidates.append(payload)

        for idx in work.index:
            if bool(s_x7_long.loc[idx]):
                add(idx, "long", f"{source_prefix}_x7_raw", t_x7.loc[idx])
            if bool(s_x6_long.loc[idx]):
                add(idx, "long", f"{source_prefix}_x6_raw", t_x6.loc[idx])
            if bool(s_x7_short.loc[idx]):
                add(idx, "short", f"{source_prefix}_x7_raw", t_x7.loc[idx])
            if bool(s_x6_short.loc[idx]):
                add(idx, "short", f"{source_prefix}_x6_raw", t_x6.loc[idx])

        if not candidates:
            self._signal_last_logged_ts[key] = work["date"].max()
            return

        conn = sqlite3.connect(self._signal_db_path(), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executemany(
                """
                INSERT OR REPLACE INTO signal_events (
                    candle_ts, pair, side, source, tag, raw_signal, safe_signal, final_entry, final_tag, close,
                    ai_rsi_14, ai_adx_14, ai_atr_pct, ai_ema_gap, ai_bb_width, ai_bb_pos,
                    ai_ret_1, ai_ret_3, ai_ret_12, ai_range_pct, ai_vol_z, ai_hour, ai_dow,
                    label_horizon_candles
                ) VALUES (
                    :candle_ts, :pair, :side, :source, :tag, :raw_signal, :safe_signal, :final_entry, :final_tag, :close,
                    :ai_rsi_14, :ai_adx_14, :ai_atr_pct, :ai_ema_gap, :ai_bb_width, :ai_bb_pos,
                    :ai_ret_1, :ai_ret_3, :ai_ret_12, :ai_range_pct, :ai_vol_z, :ai_hour, :ai_dow,
                    :label_horizon_candles
                )
                """,
                candidates,
            )
            conn.commit()
        finally:
            conn.close()
        self._signal_last_logged_ts[key] = work["date"].max()

    def _collect_mode_tags(self, strat: IStrategy, side_prefix: str) -> set[str]:
        """
        Collect only fast-mode tag families from child strategy attributes.
        """
        tags: set[str] = set()

        if side_prefix == "long_":
            allowed_attrs = {
                "long_quick_mode_tags",
                "long_rapid_mode_tags",
                "long_scalp_mode_tags",
                "long_top_coins_mode_tags",
                "long_rebuy_mode_tags",
            }
        else:
            allowed_attrs = {
                "short_quick_mode_tags",
                "short_rapid_mode_tags",
                "short_scalp_mode_tags",
                "short_top_coins_mode_tags",
                "short_rebuy_mode_tags",
            }

        for attr_name in allowed_attrs:
            if not hasattr(strat, attr_name):
                continue
            value = getattr(strat, attr_name)
            if isinstance(value, list):
                for t in value:
                    if t is not None:
                        for token in self._tag_tokens(str(t)):
                            tags.add(token)

        # Keep one proven base long tag unless explicitly disabled in config.
        if side_prefix == "long_" and self.force_tag_1_fallback:
            tags.add("1")
        return tags

    def version(self) -> str:
        """
        Calls the version() method of child strategies to get the actual version.
        """
        # 1. Get X6 version (Method call)
        if hasattr(self.strat_x6, 'version'):
            # Ideally verify if it's callable, but standard strategies use methods.
            try:
                v6 = self.strat_x6.version()
            except TypeError: 
                # If child strategy uses property instead of method
                v6 = self.strat_x6.version
        else:
            v6 = getattr(self.strat_x6, 'strategy_version', 'X6')

        # 2. Get X7 version
        if hasattr(self.strat_x7, 'version'):
            try:
                v7 = self.strat_x7.version()
            except TypeError:
                v7 = self.strat_x7.version
        else:
            v7 = getattr(self.strat_x7, 'strategy_version', 'X7')

        # 3. Final Combination
        return f"V6({v6})_V7({v7})_NostalgiaCombinedFast"
    
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.strat_x6 = NostalgiaForInfinityX6(config)
        self.strat_x7 = NostalgiaForInfinityX7(config)
        self.force_tag_1_fallback = bool(self.config.get("force_tag_1_fallback", True))
        self._signal_last_logged_ts = {}
        log.info("NostalgiaCombined Strategy Initialized (Global Whitelist + X6 Priority)")

    def _sync_child_attributes(self):
        """Sync parent environment variables to child strategies"""
        if hasattr(self, 'dp') and self.dp:
            self.strat_x6.dp = self.dp
            self.strat_x7.dp = self.dp
            
        if hasattr(self, 'wallets') and self.wallets:
            self.strat_x6.wallets = self.wallets
            self.strat_x7.wallets = self.wallets
            
        if hasattr(self, 'config') and self.config:
            self.strat_x6.config = self.config
            self.strat_x7.config = self.config
            if 'stake_currency' in self.config:
                self.strat_x6.stake_currency = self.config['stake_currency']
                self.strat_x7.stake_currency = self.config['stake_currency']

    def informative_pairs(self) -> List[Tuple]:
        self._sync_child_attributes()
        pairs_x6 = self.strat_x6.informative_pairs()
        pairs_x7 = self.strat_x7.informative_pairs()
        return list(set(pairs_x6 + pairs_x7))

    def bot_start(self, **kwargs) -> None:
        self._sync_child_attributes()
        if hasattr(self.strat_x6, "bot_start"):
            self.strat_x6.bot_start(**kwargs)
        if hasattr(self.strat_x7, "bot_start"):
            self.strat_x7.bot_start(**kwargs)

    async def _fetch_ohlcv_repaired(self, ccxt_instance, symbol, timeframe='1m', since=None, limit=None, params={}):
        """
        Patch function to fill missing candles (volume 0) for Upbit using previous close.
        """
        try:
            # 1. Call original fetch_ohlcv
            candles = await ccxt_instance._original_fetch_ohlcv(symbol, timeframe, since, limit, params)
        except Exception as e:
            raise e
        
        # Cannot correct if insufficient candles
        if not candles or len(candles) < 2:
            return candles

        # 2. Gap correction logic
        tf_ms = ccxt_instance.parse_timeframe(timeframe) * 1000
        filled_candles = []
        
        # Add first candle
        prev_candle = candles[0]
        filled_candles.append(prev_candle)
        
        for i in range(1, len(candles)):
            curr_candle = candles[i]
            prev_ts = prev_candle[0]
            curr_ts = curr_candle[0]
            expected_ts = prev_ts + tf_ms
            
            # If current candle time is ahead of expected time (Gap detected)
            while expected_ts < curr_ts:
                prev_close = prev_candle[4] 
                # [Time, Open, High, Low, Close, Volume] - Fill with volume 0.0
                dummy_candle = [expected_ts, prev_close, prev_close, prev_close, prev_close, 0.0]
                filled_candles.append(dummy_candle)
                
                expected_ts += tf_ms
                
                # Safety mechanism to prevent infinite loops
                safe_limit = limit if limit else 1000
                if len(filled_candles) > safe_limit * 2:
                    break
            
            filled_candles.append(curr_candle)
            prev_candle = curr_candle

        # Trim from the end to match requested limit
        if limit and len(filled_candles) > limit:
            return filled_candles[-limit:]
            
        return filled_candles
    
    def bot_loop_start(self, **kwargs) -> None:
        # 1. Existing logic: Sync and run child strategies
        self._sync_child_attributes()
        if hasattr(self.strat_x6, 'bot_loop_start'):
            self.strat_x6.bot_loop_start(**kwargs)
        if hasattr(self.strat_x7, 'bot_loop_start'):
            self.strat_x7.bot_loop_start(**kwargs)

        # 2. [Added] Apply CCXT Gap-Filling Patch if exchange is Upbit
        exchange_name = self.config.get('exchange', {}).get('name', '').lower()
        
        if exchange_name == 'upbit' and self.dp:
            try:
                # Get CCXT driver object
                exchange_wrapper = getattr(self.dp, '_exchange', None) or getattr(self.dp, 'exchange', None)
                if exchange_wrapper:
                    ccxt_driver = getattr(exchange_wrapper, '_api_async', None) or getattr(exchange_wrapper, '_api', None)
                    
                    # Apply patch if not already applied
                    if ccxt_driver and not hasattr(ccxt_driver, '_original_fetch_ohlcv'):
                        log.info("🔧 [Upbit Fix] Applying Gap-Filling Patch for NostalgiaCombinedFast...")
                        
                        # Backup original method
                        ccxt_driver._original_fetch_ohlcv = ccxt_driver.fetch_ohlcv
                        # Replace with patched method
                        ccxt_driver.fetch_ohlcv = types.MethodType(self._fetch_ohlcv_repaired, ccxt_driver)
                        
                        log.info("✅ [Upbit Fix] Patch Applied Successfully!")
            except Exception as e:
                log.error(f"❌ [Upbit Fix] Patch Error: {e}")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync_child_attributes()
        # [Optimization] Since X6 indicators are a subset of X7, only calculate X7
        df_x7 = self.strat_x7.populate_indicators(dataframe.copy(), metadata)
        if self._signal_learning_enabled():
            df_x7 = self._populate_signal_features(df_x7)
        return df_x7

    # -------------------------------------------------------------------------
    # 2. Smart Entry Logic - Tag-based Whitelist (No time limit)
    # -------------------------------------------------------------------------
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync_child_attributes()

        # Ensure expected columns exist.
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = ""

        # 1. Calculate indicators and signals
        with warnings.catch_warnings():
            _silence_nfi_futurewarnings()
            df_x7 = self.strat_x7.populate_entry_trend(dataframe.copy(), metadata)
            df_x6 = self.strat_x6.populate_entry_trend(dataframe.copy(), metadata)

        # Long signals
        s_x7 = self._signal_mask(df_x7, 'enter_long')
        t_x7 = df_x7['enter_tag'].fillna('')

        s_x6 = self._signal_mask(df_x6, 'enter_long')
        t_x6 = df_x6['enter_tag'].fillna('')

        # Short signals
        s_short_x7 = self._signal_mask(df_x7, 'enter_short')
        t_short_x7 = df_x7['enter_tag'].fillna('')

        s_short_x6 = self._signal_mask(df_x6, 'enter_short')
        t_short_x6 = df_x6['enter_tag'].fillna('')

        # Final result variables
        final_long_entry = Series(False, index=dataframe.index)
        final_short_entry = Series(False, index=dataframe.index)
        final_tags = Series('', index=dataframe.index)

        # -------------------------------------------------------------------------
        # [Whitelist Config] All analyzed valid tags (Time restrictions removed)
        # -------------------------------------------------------------------------
        
        # Tag sets are inherited directly from child strategies.
        SAFE_TAGS_X6 = self._collect_mode_tags(self.strat_x6, "long_")
        SAFE_TAGS_X7 = self._collect_mode_tags(self.strat_x7, "long_")
        SAFE_SHORT_TAGS_X6 = self._collect_mode_tags(self.strat_x6, "short_")
        SAFE_SHORT_TAGS_X7 = self._collect_mode_tags(self.strat_x7, "short_")

        # Clean whitespace and compare
        t_x7_clean = t_x7.str.strip()
        t_x6_clean = t_x6.str.strip()
        t_short_x7_clean = t_short_x7.str.strip()
        t_short_x6_clean = t_short_x6.str.strip()

        # Check if tags are in the whitelist for each strategy
        is_x7_safe = s_x7 & self._tag_matches_whitelist(t_x7_clean, SAFE_TAGS_X7)
        is_x6_safe = s_x6 & self._tag_matches_whitelist(t_x6_clean, SAFE_TAGS_X6)
        is_short_x7_safe = s_short_x7 & self._tag_matches_whitelist(t_short_x7_clean, SAFE_SHORT_TAGS_X7)
        is_short_x6_safe = s_short_x6 & self._tag_matches_whitelist(t_short_x6_clean, SAFE_SHORT_TAGS_X6)

        # -------------------------------------------------------------------------
        # [Entry Priority] - X6 Priority (Aggressive)
        # -------------------------------------------------------------------------

        # 1. [Top Priority] X6 Safe Signal
        # If X6 is safe, it leads regardless of X7 state
        mask_x6_safe = is_x6_safe
        
        # (1-1) Concurrent (X6 + X7) -> Use X6 tag (AND)
        mask_both = mask_x6_safe & s_x7
        final_long_entry.loc[mask_both] = True
        final_tags.loc[mask_both] = "STRAT_X6_AND " + t_x6.loc[mask_both]

        # (1-2) X6 Only -> Use X6 tag (OR)
        mask_x6_only = mask_x6_safe & (~s_x7)
        final_long_entry.loc[mask_x6_only] = True
        final_tags.loc[mask_x6_only] = "STRAT_X6_OR " + t_x6.loc[mask_x6_only]

        # 2. [Secondary] X7 Safe Signal
        # X6 not entering, only X7 is safe -> X7 leads
        mask_x7_fallback = is_x7_safe & (~is_x6_safe)

        final_long_entry.loc[mask_x7_fallback] = True
        final_tags.loc[mask_x7_fallback] = "STRAT_X7_OR " + t_x7.loc[mask_x7_fallback]

        # 3. Short side (same priority model: X6 first, then X7 fallback)
        mask_short_x6_safe = is_short_x6_safe

        mask_short_both = mask_short_x6_safe & s_short_x7
        final_short_entry.loc[mask_short_both] = True
        final_tags.loc[mask_short_both] = "STRAT_X6_AND " + t_short_x6.loc[mask_short_both]

        mask_short_x6_only = mask_short_x6_safe & (~s_short_x7)
        final_short_entry.loc[mask_short_x6_only] = True
        final_tags.loc[mask_short_x6_only] = "STRAT_X6_OR " + t_short_x6.loc[mask_short_x6_only]

        mask_short_x7_fallback = is_short_x7_safe & (~is_short_x6_safe)
        final_short_entry.loc[mask_short_x7_fallback] = True
        final_tags.loc[mask_short_x7_fallback] = "STRAT_X7_OR " + t_short_x7.loc[mask_short_x7_fallback]

        # Safety: avoid contradictory long+short on the same candle.
        conflicts = final_long_entry & final_short_entry
        final_long_entry.loc[conflicts] = False
        final_short_entry.loc[conflicts] = False
        final_tags.loc[conflicts] = ""

        # 4. Apply results
        dataframe.loc[final_long_entry, 'enter_long'] = 1
        dataframe.loc[final_short_entry, 'enter_short'] = 1
        entry_any = final_long_entry | final_short_entry
        dataframe.loc[entry_any, 'enter_tag'] = final_tags.loc[entry_any]

        self._log_signal_candidates(
            metadata,
            dataframe,
            s_x7,
            t_x7,
            s_x6,
            t_x6,
            s_short_x7,
            t_short_x7,
            s_short_x6,
            t_short_x6,
            is_x7_safe,
            is_x6_safe,
            is_short_x7_safe,
            is_short_x6_safe,
            final_long_entry,
            final_short_entry,
            final_tags,
            extra_long_x7=s_x7,
            extra_long_x6=s_x6,
            extra_short_x7=s_short_x7,
            extra_short_x6=s_short_x6,
        )

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        self._sync_child_attributes()
        df_x7 = self.strat_x7.populate_exit_trend(dataframe.copy(), metadata)
        df_x6 = self.strat_x6.populate_exit_trend(dataframe.copy(), metadata)

        x7_exit_long = self._signal_mask(df_x7, 'exit_long')
        x6_exit_long = self._signal_mask(df_x6, 'exit_long')
        x7_exit_short = self._signal_mask(df_x7, 'exit_short')
        x6_exit_short = self._signal_mask(df_x6, 'exit_short')

        dataframe['exit_long'] = (x7_exit_long | x6_exit_long).astype(int)
        dataframe['exit_short'] = (x7_exit_short | x6_exit_short).astype(int)

        if 'exit_tag' in df_x7.columns:
            dataframe['exit_tag'] = df_x7['exit_tag']
        if 'exit_tag' in df_x6.columns:
            mask_x6_exit = (x6_exit_long | x6_exit_short)
            dataframe.loc[mask_x6_exit, 'exit_tag'] = df_x6.loc[mask_x6_exit, 'exit_tag']
            
        return dataframe

    # -------------------------------------------------------------------------
    # [Tag delegation and recovery]
    # -------------------------------------------------------------------------

    def _resolve_strategy_and_tag(self, trade: Trade):
        self._sync_child_attributes()
        current_tag = trade.enter_tag if trade.enter_tag else ""
        
        # Check X6 priority
        if "STRAT_X6" in current_tag:
            strat = self.strat_x6
            original_tag = self._clean_prefixed_tag(current_tag)
            return strat, original_tag
            
        # Otherwise X7
        strat = self.strat_x7
        original_tag = self._clean_prefixed_tag(current_tag)
            
        return strat, original_tag

    @contextmanager
    def _delegated_trade_context(self, trade: Trade | None = None):
        """
        Child NFI strategies inspect both the current trade and other open trades'
        ``enter_tag`` fields (for grind/rebuy slot logic, etc.). Our wrapper prefixes
        these tags, so we temporarily expose the original tag values during delegated
        callbacks and restore them afterwards.
        """
        self._sync_child_attributes()
        patched: list[tuple[Trade, str | None]] = []
        seen: set[int] = set()

        def patch_trade_tag(target: Trade | None) -> None:
            if target is None:
                return
            key = id(target)
            if key in seen:
                return
            seen.add(key)
            original = getattr(target, "enter_tag", None)
            cleaned = self._clean_prefixed_tag(original)
            if original != cleaned:
                patched.append((target, original))
                target.enter_tag = cleaned

        patch_trade_tag(trade)
        for open_trade in Trade.get_trades_proxy(is_open=True):
            patch_trade_tag(open_trade)

        try:
            yield
        finally:
            for patched_trade, original_tag in reversed(patched):
                patched_trade.enter_tag = original_tag

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs):
        strat, original_tag = self._resolve_strategy_and_tag(trade)
        with self._delegated_trade_context(trade):
            trade.enter_tag = original_tag
            return strat.custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        strat, original_tag = self._resolve_strategy_and_tag(trade)
        with self._delegated_trade_context(trade):
            trade.enter_tag = original_tag
            if hasattr(strat, 'custom_stoploss'):
                return strat.custom_stoploss(pair, trade, current_time, current_rate, current_profit, **kwargs)

        return self.stoploss

    def custom_entry_price(self, pair: str, trade: Trade, current_time: datetime, proposed_rate: float,
                           entry_tag: str, side: str, **kwargs) -> float:
        if entry_tag and "STRAT_X6" in entry_tag:
            strat = self.strat_x6
            clean_tag = self._clean_prefixed_tag(entry_tag)
        else:
            strat = self.strat_x7
            clean_tag = self._clean_prefixed_tag(entry_tag)

        with self._delegated_trade_context(trade):
            return strat.custom_entry_price(pair, trade, current_time, proposed_rate, clean_tag, side, **kwargs)

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        strat, original_tag = self._resolve_strategy_and_tag(trade)
        with self._delegated_trade_context(trade):
            trade.enter_tag = original_tag
            if hasattr(strat, 'confirm_trade_exit'):
                return strat.confirm_trade_exit(pair, trade, order_type, amount, rate, time_in_force, exit_reason, current_time, **kwargs)

        return True

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs):
        
        strat, original_tag = self._resolve_strategy_and_tag(trade)
        with self._delegated_trade_context(trade):
            trade.enter_tag = original_tag
            if hasattr(strat, 'adjust_trade_position'):
                return strat.adjust_trade_position(
                    trade, current_time, current_rate, current_profit,
                    min_stake, max_stake, current_entry_rate, current_exit_rate,
                    current_entry_profit, current_exit_profit, **kwargs
                )

        return None

    def order_filled(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> None:
        strat, original_tag = self._resolve_strategy_and_tag(trade)
        with self._delegated_trade_context(trade):
            trade.enter_tag = original_tag
            if hasattr(strat, "order_filled"):
                strat.order_filled(pair, trade, order, current_time, **kwargs)
        return None

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str,
                            side: str, **kwargs) -> bool:
        
        if entry_tag and "STRAT_X6" in entry_tag:
            strat = self.strat_x6
            clean_tag = self._clean_prefixed_tag(entry_tag)
        else:
            strat = self.strat_x7
            clean_tag = self._clean_prefixed_tag(entry_tag)

        with self._delegated_trade_context():
            if hasattr(strat, 'confirm_trade_entry'):
                return strat.confirm_trade_entry(pair, order_type, amount, rate, time_in_force, 
                                                 current_time, clean_tag, side, **kwargs)
        
        return True

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        
        if entry_tag and "STRAT_X6" in entry_tag:
            strat = self.strat_x6
            clean_tag = self._clean_prefixed_tag(entry_tag)
        else:
            strat = self.strat_x7
            clean_tag = self._clean_prefixed_tag(entry_tag)

        with self._delegated_trade_context():
            if hasattr(strat, 'leverage'):
                 return strat.leverage(pair, current_time, current_rate, proposed_leverage, 
                                       max_leverage, clean_tag, side, **kwargs)
        
        return 1.0

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float, max_stake: float,
                            leverage: float, entry_tag: str, side: str, **kwargs) -> float:

        if entry_tag and "STRAT_X6" in entry_tag:
            strat = self.strat_x6
            clean_tag = self._clean_prefixed_tag(entry_tag)
        else:
            strat = self.strat_x7
            clean_tag = self._clean_prefixed_tag(entry_tag)

        with self._delegated_trade_context():
            if hasattr(strat, 'custom_stake_amount'):
                return strat.custom_stake_amount(pair, current_time, current_rate, proposed_stake,
                                                 min_stake, max_stake, leverage, clean_tag, side, **kwargs)
        
        return proposed_stake
