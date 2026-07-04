"""
market_levels.py

Computes the key reference price levels the liquidity sweep strategy
trades around, from raw OHLCV bars:

    PMH  - Premarket High
    PML  - Premarket Low
    PDH  - Previous Day High
    PDL  - Previous Day Low
    VWAP - Session Volume Weighted Average Price (resets each session)

All functions expect a pandas DataFrame with at least these columns:
    ["timestamp", "open", "high", "low", "close", "volume"]
`timestamp` must be a tz-aware pandas datetime (any timezone); it will
be converted internally to the configured trading timezone (default
America/New_York) for session/premarket windowing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _validate_bars(bars: pd.DataFrame) -> None:
    """Raise a clear error if `bars` is missing required columns.

    Args:
        bars: OHLCV DataFrame to validate.

    Raises:
        ValueError: If any required column is missing or the frame is
            empty.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"bars is missing required columns: {missing}")
    if bars.empty:
        raise ValueError("bars is empty; cannot compute market levels")


def _localize(bars: pd.DataFrame, timezone: str) -> pd.Series:
    """Return the `timestamp` column converted to the given timezone.

    Args:
        bars: OHLCV DataFrame with a `timestamp` column.
        timezone: IANA timezone name, e.g. "America/New_York".

    Returns:
        A tz-aware datetime Series in the target timezone.

    Raises:
        ValueError: If `timestamp` is not tz-aware.
    """
    ts = bars["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        ts = pd.to_datetime(ts)
    if ts.dt.tz is None:
        raise ValueError(
            "bars['timestamp'] must be tz-aware (localize to UTC or the "
            "exchange timezone before calling market_levels functions)"
        )
    return ts.dt.tz_convert(timezone)


@dataclass
class MarketLevels:
    """Computes PMH/PML/PDH/PDL/VWAP from OHLCV bars.

    Attributes:
        timezone: IANA timezone used to determine premarket/session
            windows. Defaults to "America/New_York".
        premarket_start: Premarket window start, "HH:MM" 24h format.
        premarket_end: Premarket window end, "HH:MM" 24h format (this is
            exclusive of regular session bars, i.e. up to but not
            including the regular-session open).
    """

    timezone: str = "America/New_York"
    premarket_start: str = "04:00"
    premarket_end: str = "09:30"

    def premarket_high_low(self, bars: pd.DataFrame) -> tuple[float, float]:
        """Compute the premarket high and low for the most recent
        trading day present in `bars`.

        Args:
            bars: OHLCV DataFrame covering at least the premarket window
                of the day in question.

        Returns:
            (premarket_high, premarket_low) as floats.

        Raises:
            ValueError: If `bars` is invalid, or no bars fall within the
                premarket window for the most recent date in `bars`.
        """
        _validate_bars(bars)
        local_ts = _localize(bars, self.timezone)
        most_recent_date = local_ts.dt.date.max()

        same_day = local_ts.dt.date == most_recent_date
        time_of_day = local_ts.dt.strftime("%H:%M")
        in_premarket = (time_of_day >= self.premarket_start) & (
            time_of_day < self.premarket_end
        )
        mask = same_day & in_premarket

        pm_bars = bars.loc[mask]
        if pm_bars.empty:
            raise ValueError(
                f"No premarket bars found between {self.premarket_start} "
                f"and {self.premarket_end} {self.timezone} for "
                f"{most_recent_date}"
            )
        return float(pm_bars["high"].max()), float(pm_bars["low"].min())

    def previous_day_high_low(self, bars: pd.DataFrame) -> tuple[float, float]:
        """Compute the prior regular session's high and low.

        The "previous day" is defined as the most recent calendar date
        in `bars` that is strictly before the latest date present, using
        only bars at/after the premarket_end time (i.e. the regular
        session, not premarket, of that prior day).

        Args:
            bars: OHLCV DataFrame covering at least two trading days.

        Returns:
            (previous_day_high, previous_day_low) as floats.

        Raises:
            ValueError: If `bars` is invalid, only one trading day is
                present, or no regular-session bars exist for the prior
                day.
        """
        _validate_bars(bars)
        local_ts = _localize(bars, self.timezone)
        dates = sorted(local_ts.dt.date.unique())
        if len(dates) < 2:
            raise ValueError(
                "previous_day_high_low requires at least two distinct "
                "trading days of bars"
            )
        previous_date = dates[-2]

        same_day = local_ts.dt.date == previous_date
        time_of_day = local_ts.dt.strftime("%H:%M")
        regular_session = time_of_day >= self.premarket_end
        mask = same_day & regular_session

        prior_bars = bars.loc[mask]
        if prior_bars.empty:
            raise ValueError(
                f"No regular-session bars found for previous day "
                f"{previous_date}"
            )
        return float(prior_bars["high"].max()), float(prior_bars["low"].min())

    def session_vwap(self, bars: pd.DataFrame) -> pd.Series:
        """Compute a running (cumulative) VWAP for the most recent
        trading day's regular session, reset at session start.

        VWAP_t = cumsum(typical_price * volume)_t / cumsum(volume)_t
        where typical_price = (high + low + close) / 3.

        Args:
            bars: OHLCV DataFrame covering the most recent day's regular
                session bars (and optionally other days/premarket, which
                will be excluded).

        Returns:
            A pandas Series aligned to the regular-session bars of the
            most recent day, in chronological order, containing the
            running VWAP. Bars with zero cumulative volume are NaN.

        Raises:
            ValueError: If `bars` is invalid or no regular-session bars
                exist for the most recent day.
        """
        _validate_bars(bars)
        local_ts = _localize(bars, self.timezone)
        most_recent_date = local_ts.dt.date.max()

        same_day = local_ts.dt.date == most_recent_date
        time_of_day = local_ts.dt.strftime("%H:%M")
        regular_session = time_of_day >= self.premarket_end
        mask = same_day & regular_session

        session_bars = bars.loc[mask].sort_values("timestamp")
        if session_bars.empty:
            raise ValueError(
                f"No regular-session bars found for {most_recent_date}"
            )

        typical_price = (
            session_bars["high"] + session_bars["low"] + session_bars["close"]
        ) / 3.0
        pv = typical_price * session_bars["volume"]
        cum_pv = pv.cumsum()
        cum_vol = session_bars["volume"].cumsum()
        vwap = cum_pv / cum_vol
        vwap.index = session_bars.index
        return vwap

    def compute_all(self, bars: pd.DataFrame) -> dict:
        """Convenience wrapper computing PMH, PML, PDH, PDL, and VWAP.

        Args:
            bars: OHLCV DataFrame covering at least the premarket and
                regular session of the current day, plus the prior
                day's regular session (for PDH/PDL).

        Returns:
            A dict with keys "PMH", "PML", "PDH", "PDL" (floats) and
            "VWAP" (a pandas Series). If PDH/PDL cannot be computed
            (e.g. only one day of data is available), those keys will
            be None rather than raising, so the caller can still trade
            off of PMH/PML/VWAP alone.
        """
        pmh, pml = self.premarket_high_low(bars)
        vwap = self.session_vwap(bars)
        try:
            pdh, pdl = self.previous_day_high_low(bars)
        except ValueError:
            pdh, pdl = None, None
        return {"PMH": pmh, "PML": pml, "PDH": pdh, "PDL": pdl, "VWAP": vwap}
