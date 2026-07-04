"""
watchlist.py

Builds the tradable symbol list for a trading session by combining a
static candidate list with live price/market-cap filters, and tracks
the QQQ confirmation symbol separately (it is never itself traded by
the sweep strategy, only used as a directional filter).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Watchlist:
    """Filters a candidate symbol universe down to tradable symbols.

    Attributes:
        candidates: Static list of candidate ticker symbols.
        confirmation_symbol: Symbol used for directional confirmation
            (e.g. "QQQ"). Excluded from the tradable output even if it
            also appears in `candidates`.
        min_price: Minimum last price required for a symbol to be
            eligible (dollars).
        min_market_cap: Minimum market capitalization required for a
            symbol to be eligible (dollars).
    """

    candidates: list[str]
    confirmation_symbol: str
    min_price: float
    min_market_cap: float
    _tradable: list[str] = field(default_factory=list, init=False, repr=False)

    def is_eligible(self, symbol: str, price: float, market_cap: float) -> bool:
        """Check whether a single symbol passes the universe filters.

        Args:
            symbol: Ticker symbol being evaluated.
            price: Current/last price for the symbol.
            market_cap: Current market capitalization for the symbol.

        Returns:
            True if price > min_price and market_cap > min_market_cap
            and the symbol is not the confirmation symbol. False
            otherwise.
        """
        if symbol == self.confirmation_symbol:
            return False
        return price > self.min_price and market_cap > self.min_market_cap

    def refresh(
        self,
        price_lookup: dict[str, float],
        market_cap_lookup: dict[str, float],
    ) -> list[str]:
        """Recompute the tradable symbol list for today.

        Candidates missing from either lookup are skipped (treated as
        ineligible) rather than raising, since a temporarily-missing
        data point for one symbol shouldn't halt the whole scan.

        Args:
            price_lookup: Mapping of symbol -> current/last price.
            market_cap_lookup: Mapping of symbol -> market capitalization.

        Returns:
            The filtered, tradable list of symbols (order preserved
            from `self.candidates`). Also stored on the instance and
            retrievable via `tradable_symbols`.
        """
        tradable: list[str] = []
        for symbol in self.candidates:
            price = price_lookup.get(symbol)
            market_cap = market_cap_lookup.get(symbol)
            if price is None or market_cap is None:
                continue
            if self.is_eligible(symbol, price, market_cap):
                tradable.append(symbol)

        self._tradable = tradable
        return tradable

    @property
    def tradable_symbols(self) -> list[str]:
        """Return the tradable symbols computed by the last `refresh()` call.

        Returns:
            A list of ticker symbols. Empty list if `refresh()` has not
            been called yet.
        """
        return list(self._tradable)
