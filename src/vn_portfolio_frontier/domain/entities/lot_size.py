"""Lot size rules for Vietnamese stock exchanges (NFR-R-02 compliance).

Enforces that order quantities are integer multiples of the applicable lot size
on the trade date, per exchange regulation. Vietnamese market lot history:

- HSX (HoSE): 10 shares pre-2021-01-04 -> 100 shares from 2021-01-04
  (Quyet dinh 496/QD-SGDHCM, HoSE 04/01/2021 - lot reform).
- HNX / UPCoM: 100 shares consistently (per HNX Quy che giao dich).

Design: round-down conservative. Fractional shares dropped (not added back to
cash) to prevent over-trade bias at trigger date when cash may be constrained.
Alternative round-up rejected per ADR-012 (cost preservation vs trade feasibility).

VN30 universe is 100% HSX; HNX/UPCoM rules kept extensible for thesis Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class LotSizeRule:
    """Immutable lot size rule for a given exchange + effective date range.

    Attributes:
        exchange: 'HSX' | 'HNX' | 'UPCoM'
        lot_size: shares per minimum tradable lot
        effective_from: inclusive start date
        effective_to: inclusive end date, or None if currently effective
        legal_source: human-readable citation (QD number, article)
    """

    exchange: str
    lot_size: int
    effective_from: date
    effective_to: date | None = None
    legal_source: str = ""

    def applies_on(self, trade_date: date) -> bool:
        """Return True if this rule is in effect on the given trade date."""
        return trade_date >= self.effective_from and (
            self.effective_to is None or trade_date <= self.effective_to
        )


# HSX rule history: 10 -> 100 shares reform (04/01/2021).
# Pre-2021 rule kept defensively; P1 data starts 2021-01-04 so unused in practice.
HSX_LOT_RULES: tuple[LotSizeRule, ...] = (
    LotSizeRule(
        exchange="HSX",
        lot_size=10,
        effective_from=date(2015, 1, 1),
        effective_to=date(2021, 1, 3),
        legal_source="HSX pre-reform (10-share lot, pre-2021)",
    ),
    LotSizeRule(
        exchange="HSX",
        lot_size=100,
        effective_from=date(2021, 1, 4),
        effective_to=None,
        legal_source="Quyet dinh 496/QD-SGDHCM, HoSE 04/01/2021",
    ),
)

# Future extension: HNX_LOT_RULES, UPCOM_LOT_RULES when thesis Phase 2 expands universe
_EXCHANGE_RULES: dict[str, tuple[LotSizeRule, ...]] = {
    "HSX": HSX_LOT_RULES,
}


def get_lot_size(exchange: str, trade_date: date) -> int:
    """Return the applicable lot size (shares) for an exchange on a trade date.

    Args:
        exchange: Market code, e.g. 'HSX'.
        trade_date: Date of the hypothetical trade.

    Returns:
        Positive integer lot size.

    Raises:
        ValueError: If no rule covers the exchange or date (unsupported market
            or date outside all known rule ranges).
    """
    rules = _EXCHANGE_RULES.get(exchange)
    if rules is None:
        raise ValueError(
            f"No lot rules defined for exchange {exchange!r}. "
            f"Supported: {list(_EXCHANGE_RULES.keys())}"
        )
    for rule in rules:
        if rule.applies_on(trade_date):
            return rule.lot_size
    raise ValueError(
        f"No applicable lot rule for {exchange} on {trade_date}. "
        f"Check rule effective_from/effective_to coverage."
    )


def round_to_lot(target_shares: Decimal, lot_size: int) -> int:
    """Round target share count DOWN to nearest lot multiple (conservative).

    Fractional and odd shares are DROPPED (not added back to cash), aligning
    with ADR-012 cost-preservation principle. Returns 0 if target is below
    one full lot (position considered too small to open).

    Args:
        target_shares: Non-negative Decimal share count from strategy output.
        lot_size: Positive integer lot size (from get_lot_size).

    Returns:
        Non-negative integer, multiple of lot_size, <= target_shares.

    Raises:
        ValueError: If lot_size <= 0.
    """
    if lot_size <= 0:
        raise ValueError(f"lot_size must be positive, got {lot_size}")
    if target_shares <= 0:
        return 0
    whole_lots = int(target_shares // Decimal(lot_size))
    return whole_lots * lot_size
