"""CostCalculator — compute TradingCost cho một tập Order per ADR-012.

Cost model theo ADR-012 (user-parameterized, cost-agnostic framework):

    brokerage = sum_over_all_orders(gross_amount × brokerage_pct)
    slippage  = sum_over_all_orders(gross_amount × market_impact_bps / 10000)
    tax       = sum_over_SELL_orders(gross_amount × tax_pct)
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                      Thông tư 111/2013/TT-BTC seller-only

Where:
    gross_amount = order.shares × order.est_price
    brokerage_pct: user-input broker commission (0.0015 = 0.15%)
    market_impact_bps: VN30 liquid default 10 bps (0.10%); override for small-cap
    tax_pct: Vietnam seller tax default 0.001 (0.1%); invariant per Thông tư

ADR-012 cost-field mapping (F-M3)
---------------------------------
Explicit mapping between ADR-012 component names, Python parameters, default
values, and primary sources. Reviewers can cross-check implementation vs ADR
line-by-line.

    ADR-012 component   | Python parameter      | Default         | Applies to | Source
    --------------------+-----------------------+-----------------+------------+------------------------------
    Broker commission   | brokerage_pct         | user-input      | BUY + SELL | VCBS 0.0015, SSI 0.0025 (2026)
    Market impact       | market_impact_bps     | 10 bps          | BUY + SELL | VN30 Amihud illiq proxy
    Transfer tax        | tax_pct               | Decimal("0.001")| SELL only  | Thông tư 111/2013/TT-BTC §12
    (seller only)       |                       |                 |            |
    Gross trade value   | order.gross_amount()  | shares x price  | per order  | ADR-012 §3.1 definition
    Settlement precision| NUMERIC(20, 2)        | VND quantum 0.01| final sum  | Migration 005 schema +
                        |                       |                 |            | NFR-R-07 Decimal invariant

ADR-012 formula (§3.2) in matching Python shape:

    brokerage = SUM_{o in orders}      gross_amount(o) * brokerage_pct
    slippage  = SUM_{o in orders}      gross_amount(o) * market_impact_bps / 10_000
    tax       = SUM_{o | o.side=SELL}  gross_amount(o) * tax_pct

All three sums quantized to VND (ROUND_HALF_UP, 2 decimals) before return.

Design decisions:
    - Pure domain service (no I/O): instantiated once per RebalanceRun with
      the user-input parameters, injected into BaseStrategy via constructor.
      This is the Repository Pattern's cost-model equivalent — swap in a
      different CostCalculator (e.g., AlmgrenChrisCostCalculator in Sprint
      14+) without touching strategy code.
    - All math in Decimal: NFR-R-07 deterministic reproducibility across
      backtest runs; float would drift when summing 1250+ days of costs.
    - Quantize final components to VND (2 decimal places HALF_UP) at return:
      matches NUMERIC(20, 2) schema in simulation.rebalance_decision; avoids
      Decimal('126666.6666666...') noise in persisted rows.
    - Validation at __init__: fail-fast when invalid parameters, not when
      first compute() call. Test seed configuration bugs early.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
from vn_portfolio_frontier.domain.entities.rebalance_decision import TradingCost

# VND quantization: 2 decimal places matches NUMERIC(20, 2) schema
_VND_QUANTUM = Decimal("0.01")

# Default parameters match Migration 005 schema defaults (ADR-012 L1)
_DEFAULT_MARKET_IMPACT_BPS = 10
_DEFAULT_TAX_PCT = Decimal("0.001")  # 0.1% Thông tư 111/2013/TT-BTC

# Validation bounds (ADR-012 realistic ranges)
_MAX_BROKERAGE_PCT = Decimal("0.01")  # 1% (actual CTCK range 0.03-0.40%)
_MAX_MARKET_IMPACT_BPS = 500  # 5% (small-cap worst case)
_MAX_TAX_PCT = Decimal("0.01")  # 1% ceiling (regulation changes future-proof)


class CostCalculator:
    """Compute execution cost breakdown cho một tập Order.

    Parameters
    ----------
    brokerage_pct : Decimal
        User-input broker commission rate (0.0015 = 0.15% of gross).
        Must be in [0, 0.01] range. Zero valid cho zero-fee brokers (DNSE,
        Pinetree) but system still adds phí sở HSX minimum via Simulator-level
        patch, not here.
    market_impact_bps : int, default 10
        Market-impact assumption in basis points. VN30 liquid tickers default
        10 bps (0.10%); small-cap override up to 100 bps. Range [0, 500].
    tax_pct : Decimal, default Decimal("0.001")
        Vietnam seller tax rate per Thông tư 111/2013/TT-BTC. 0.1% invariant
        for retail; funds exempt (set 0). Range [0, 0.01].

    Raises
    ------
    ValueError
        If any parameter is out of range.

    Examples
    --------
    >>> from decimal import Decimal
    >>> from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
    >>> calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
    >>> orders = [
    ...     Order("VCB", OrderSide.BUY, 100, Decimal("125000")),
    ...     Order("FPT", OrderSide.SELL, 50, Decimal("95000")),
    ... ]
    >>> cost = calc.compute(orders)
    >>> cost.brokerage  # (12500000 + 4750000) × 0.0015
    Decimal('25875.00')
    >>> cost.slippage   # (12500000 + 4750000) × 10 / 10000
    Decimal('17250.00')
    >>> cost.tax        # 4750000 × 0.001 (SELL only)
    Decimal('4750.00')
    """

    def __init__(
        self,
        brokerage_pct: Decimal,
        market_impact_bps: int = _DEFAULT_MARKET_IMPACT_BPS,
        tax_pct: Decimal = _DEFAULT_TAX_PCT,
    ) -> None:
        if not (Decimal("0") <= brokerage_pct <= _MAX_BROKERAGE_PCT):
            raise ValueError(
                f"CostCalculator.brokerage_pct must be in [0, {_MAX_BROKERAGE_PCT}], "
                f"got {brokerage_pct}. Hint: 0.0015 = 0.15%, not 15 bps."
            )
        if not (0 <= market_impact_bps <= _MAX_MARKET_IMPACT_BPS):
            raise ValueError(
                f"CostCalculator.market_impact_bps must be in [0, {_MAX_MARKET_IMPACT_BPS}], "
                f"got {market_impact_bps}"
            )
        if not (Decimal("0") <= tax_pct <= _MAX_TAX_PCT):
            raise ValueError(
                f"CostCalculator.tax_pct must be in [0, {_MAX_TAX_PCT}], "
                f"got {tax_pct}. Vietnam retail default 0.001 (0.1%)."
            )

        self.brokerage_pct = brokerage_pct
        self.market_impact_bps = market_impact_bps
        self.tax_pct = tax_pct

    def compute(self, orders: Iterable[Order]) -> TradingCost:
        """Return the aggregated TradingCost cho một tập Order.

        Parameters
        ----------
        orders : Iterable[Order]
            Orders to compute cost for. Empty iterable returns TradingCost.zero().

        Returns
        -------
        TradingCost
            Aggregated breakdown. All three components quantized to VND
            (2 decimal places HALF_UP). Non-negative.

        Notes
        -----
        - Brokerage: applied to BOTH BUY and SELL (CTCK charges both legs)
        - Slippage: applied to BOTH sides (market impact of execution)
        - Tax: SELL-only (seller tax per Thông tư 111/2013/TT-BTC)
        - If orders is empty, returns zero cost (not a no-op; TradingCost
          validation requires non-negative which zero satisfies)
        """
        brokerage_raw = Decimal("0")
        slippage_raw = Decimal("0")
        tax_raw = Decimal("0")

        bps_divisor = Decimal(10000)

        for order in orders:
            gross = order.gross_amount()

            brokerage_raw += gross * self.brokerage_pct
            slippage_raw += gross * Decimal(self.market_impact_bps) / bps_divisor

            if order.side == OrderSide.SELL:
                tax_raw += gross * self.tax_pct

        return TradingCost(
            brokerage=brokerage_raw.quantize(_VND_QUANTUM, rounding=ROUND_HALF_UP),
            slippage=slippage_raw.quantize(_VND_QUANTUM, rounding=ROUND_HALF_UP),
            tax=tax_raw.quantize(_VND_QUANTUM, rounding=ROUND_HALF_UP),
        )
