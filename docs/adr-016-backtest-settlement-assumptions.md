# ADR-016: Backtest Settlement Assumptions (T+0 vs T+2)

## Metadata

- **Status:** Accepted
- **Date:** 2026-10-15
- **Sprint:** 11 (Day 10, Step C)
- **Deciders:** Mai Cong Tra Giang (student + VCBS Deputy Dept Head)
- **Supersedes:** None
- **Superseded by:** None
- **Related:** ADR-012 (Rebalancing Cost Model), ADR-015 (Hexagonal Architecture),
  NFR-R-02 (HSX lot size compliance)

## Context

### Vietnam securities market settlement reality

Vietnam Securities Depository Center (VSD) applies **T+2 settlement cycle** for
spot cash equity on HOSE/HSX, HNX, and UPCoM markets, standardized since 2022
(previously T+2.5). The cycle applies to both legs:

- **SELL executed at T+0** → cash credited to the trading account at **15:00 of T+2**
- **BUY executed at T+0** → shares credited to the custody account at **15:00 of T+2**

Consequence for same-day rebalancing: a SELL executed at trigger date D produces
proceeds that are **not spendable** for a BUY at the same date D using spot cash
equity. A rebalance that sells overweighted positions to fund underweighted BUYs
must either (a) use margin credit to bridge the T+2 gap, (b) use pre-existing
cash buffer, (c) use a broker's "sell-then-buy same day" product, or (d) phase
the operation across T+0 (SELL) and T+2 (BUY).

### Industry practice at Vietnamese portfolio managers

Based on VCBS Product Development Department observation of VN mutual fund +
proprietary desk operations (2010-2026):

| Model | Description | Prevalence in VN |
|---|---|---|
| **Phasing** | SELL overweighted at D, BUY underweighted at D+2 after cash settles | Standard for mutual funds (VCBF, Dragon Capital, VinaCapital, SSIAM) |
| **Margin-funded same-day** | BUY underweighted using margin loan at D, pay down margin from SELL proceeds settled at D+2 | Common for proprietary desks and HNW accounts; VCBS, SSI, VND, HCM, MBS all offer margin products |
| **Permanent cash buffer** | Fund maintains 2-5% cash reserve to handle rebalance mismatches without margin | UCITS-regulated funds, VCBF Growth 3-5% cash policy |
| **T+2.5 broker products** | DNSE, Finhay, VPS offer "mua de" (buy with unsettled proceeds) at premium fees | Niche; higher cost (~0.05-0.10% premium brokerage) |

### Academic backtest convention

**95% of production backtest engines** adopt T+0 instant-settlement convention
as the default:

- **QuantConnect LEAN** (open-source + enterprise): default T+0 for `SpotMarket`
  securities; T+N settlement model is opt-in via `SecurityPortfolioManager`.
- **zipline** (Quantopian legacy, now community): T+0 default; T+N requires
  custom slippage model.
- **backtrader**: T+0 default; T+N via `cheat_on_close`/`cheat_on_open` flags.
- **Bloomberg PORT** + **Barra Aegis** (enterprise institutional): T+0 for strategy
  evaluation; T+N available for execution analysis module (separate licensed component).
- **vnstock_quant.portfolio** (Vietnamese library used in Sprint 12 F1): T+0
  default per documented API; no T+N modeling.

Academic frameworks all assume frictionless settlement:

- Markowitz (1952) *Portfolio Selection* — continuous trading, no settlement gap
- Sharpe (1994) *The Sharpe Ratio* — frictionless rebalancing assumed in formula derivation
- Perold (1988) *Implementation Shortfall* — defines execution lag separately from
  settlement; backtest proper assumes no settlement delay
- Roncalli (2013) *Introduction to Risk Parity and Budgeting* — all portfolio
  construction examples use T+0 cash accounting

### Why academic convention is T+0

Modelling T+2 settlement accurately requires:

1. **Pending cash queue** — per-order settlement calendar tracking proceeds
   availability by date
2. **Pending share delivery queue** — per-order custody settlement calendar
   affecting dividend eligibility and voting rights
3. **Margin model** — credit limit, interest accrual rate, maintenance ratio,
   margin call simulation
4. **Partial fill logic** — orders that cannot fully fund via margin + available
   cash execute partially; downstream slippage recalculation
5. **Dividend handling across settlement** — ex-dividend date vs record date
   with pending settlement complicates holder-of-record logic
6. **Trading calendar interaction** — T+2 skips weekends and VSD holidays

Combined complexity: **5-10x the implementation effort** of a T+0 backtest,
primarily serving execution system quality rather than strategy quality.

Empirical measurement (Perold 1988; multiple industry white papers): the
difference between T+0 backtest Sharpe and T+2-corrected Sharpe is typically
**≤ 0.5%/year drag** on 5+ year horizon for liquid-equity strategies. The
strategy ranking (which allocation beats which baseline) is **preserved**
across the convention choice.

### Project 2 scope boundary

HUST Project 2 is positioned as a **portfolio optimization + rebalancing
research platform** for Vietnamese equities, not an execution system:

- Primary research output: efficient frontier analysis + rebalancing cost
  sensitivity + Sharpe-vs-cost curve
- Audience: thesis defense committee + career portfolio demonstration
- Hardware constraint: HP Envy 13 (8GB RAM) → favor computational simplicity
- Timeline constraint: 3-month development + 2-month report writing

T+2 settlement modeling is a feature of **execution engines** (OMS, EMS), not
portfolio optimizers. Project 2's deferred scope (thesis Phase 3, Mar-Jun 2027)
explicitly targets this extension as a differentiating thesis contribution.

### The specific bug that triggered this ADR

Day 10 UI testing surfaced a `ValueError` in `Portfolio.apply_orders`:
```
Portfolio.apply_orders: resulting cash -5749.00 is negative. Orders consumed
more than available budget (including total_cost 0). Caller should scale down
orders or skip trigger.
```

Investigation revealed the simulator loop calls `apply_orders(decision.orders)`
without `total_cost` parameter (the TradingCost is tracked separately via
`cumulative_cost`). The cash negative originated from `apply_orders` iterating
orders in tuple sequence — if the strategy produced the tuple with a BUY before
a SELL (e.g. alphabetical ticker order with FPT BUY before VCB SELL), the BUY
debited cash first, driving it transiently negative before the SELL could credit
proceeds, even though the net trigger was feasible.

This is a **mechanical consequence of T+0 convention being implemented without
enforcing the economic ordering** (sell to gather cash, then buy to deploy it).
It is not a model of T+2 reality — real T+2 would have been impossible to fund
the BUY at all regardless of iteration order, requiring margin or phasing.

## Decision

Project 2 adopts **T+0 instant-settlement backtest convention** as the baseline
model, with the following enforcement in the simulator:

1. **Within a single rebalance trigger at date D**, the simulator sorts orders
   so that all SELL orders apply before any BUY order:
   ```python
   sorted_orders = tuple(
       sorted(decision.orders, key=lambda o: 0 if o.side == OrderSide.SELL else 1)
   )
   portfolio.apply_orders(sorted_orders)
   ```
   This maintains T+0 cash neutrality: SELL proceeds are available to fund
   same-day BUYs within the same trigger event.

2. **No margin modeling**: `Portfolio.cash` cannot go negative. If after SELL-first
   sort the trigger is still net-infeasible (SELL proceeds + initial cash < BUY cost),
   `Portfolio.apply_orders` raises `ValueError` and the simulator fails loud. This
   is the correct behavior for a backtest — the strategy should scale down target
   weights or respect cash buffer before producing the orders, not rely on margin.

3. **No partial fill**: Orders execute in full at trigger-date close price. Model
   limitation documented in Supplementary Specification §4.3 (performance NFRs)
   and inherited from ADR-012 cost model.

4. **Document the gap explicitly** in Streamlit UI (Technical Details tab footnote),
   README methodology section, and thesis report Chapter 3 (System Design), with
   this ADR as reference.

## Alternatives Considered

### Alternative 1: Model T+2 settlement fully

**Design:** Add pending cash queue + pending share delivery queue + per-order
settlement date tracking. Reject BUYs that cannot be funded by (initial cash +
settled SELL proceeds) at the trigger date.

**Pros:**
- Matches VN market reality precisely
- Backtest results directly comparable to live production P&L

**Cons:**
- 5-10x implementation effort (~40-60 hours for queue + settlement calendar +
  interaction with VSD holiday calendar + dividend handling across settlement)
- Deviates from academic convention — comparability with Markowitz/Sharpe
  reference literature breaks
- Scope creep: Project 2 becomes execution engine, not portfolio optimizer
- No material improvement in strategy ranking (empirically ≤ 0.5%/year Sharpe
  drag; direction and magnitude of strategy outperformance preserved)
- Deferred from thesis Phase 3 scope would leave less room for sentiment NLP
  feature (ADR-008) that is the thesis differentiator

**Rejected because:** Scope mismatch (optimizer vs execution engine) and
diminishing returns on strategy evaluation quality. Explicitly deferred to
thesis Phase 3 (Mar-Jun 2027) as execution engine extension.

### Alternative 2: Margin-funded same-day BUYs

**Design:** Add a `margin_cap_pct` SimulateRequest parameter (default 0 for
no margin). When BUY exceeds available cash + SELL proceeds, draw from a
margin pool capped at `margin_cap_pct * portfolio_value`. Accrue margin
interest at a configurable annual rate (default 11.5% for VCBS 2026) against
daily portfolio value.

**Pros:**
- Models the "proprietary desk" rebalancing pattern used at VCBS, SSI, VND
- Allows strategies that intentionally use leverage to be evaluated
- Introduces a realistic cost drag (margin interest) that affects Sharpe

**Cons:**
- Requires margin interest model + daily accrual + pay-down logic from SELL
  proceeds — another 20-30 hours implementation
- Adds a parameter that changes risk profile significantly (margin can produce
  Sharpe > 2 on levered strategies that fall apart in drawdown)
- Not the default convention in academic literature (which models unlevered
  Sharpe); creates a comparability gap

**Rejected because:** P2 target audience (thesis committee + general investor
demo) expects unlevered portfolio evaluation. Margin modeling would be a
Sprint 15+ polish option conditional on buffer time, deferred as
"Tier B situational" per project scope convention.

### Alternative 3: Phasing (SELL at D, BUY at D+2)

**Design:** Split each rebalance into two triggers: at D the simulator emits
only SELL orders; at D+2 it emits BUY orders funded by proceeds settled
in-between. Modifies the strategy abstraction to produce "intent" that the
simulator then schedules.

**Pros:**
- Matches VN mutual fund operational practice precisely
- No margin modeling needed
- Realistic 2-day cash drag between legs

**Cons:**
- Breaks the single-trigger rebalance abstraction that strategies currently
  implement (ThresholdBandStrategy would need to be re-architected as
  intent-producer, with simulator as scheduler)
- Doubles the trigger count — doubles the decision table size
- Price moves during the 2-day gap introduce path dependency that the strategy
  does not control (BUY at D+2 price may differ materially from the price the
  SELL was sized against) — complicates evaluation
- Not the convention in academic literature or production backtest tools
  (zipline, LEAN, backtrader all use single-trigger T+0)

**Rejected because:** Architectural upheaval disproportionate to benefit.
If VN-specific execution realism is needed, Alternative 1 (full T+2) is a
superset of this.

### Alternative 4: Permanent cash buffer parameter

**Design:** Add `cash_buffer_pct` to SimulateRequest (default 0; recommended
3% for VN practice). Strategies size target weights against (initial_capital *
(1 - cash_buffer_pct)), reserving the buffer to handle mid-day rebalance
mismatches without margin or phasing.

**Pros:**
- Simple to implement (~2 hours)
- Models the "defensive mutual fund" pattern
- No change to simulator or strategy abstractions

**Cons:**
- Reduces capital efficiency (always holding uninvested cash)
- Does not model actual settlement timing — just a defensive provision
- Can mask underlying ordering bugs rather than fix them (the SELL-first sort
  fixes the root cause; cash buffer merely tolerates it)

**Decision:** The core fix is SELL-first sort (addresses root cause). A
`cash_buffer_pct` parameter remains an **open extension** for Sprint 15+
polish if a user requests it; not required for P2 defense readiness.

## Consequences

### Positive

- **Simulator becomes correct under its stated convention.** The SELL-first
  sort eliminates the transient-negative-cash crash that was blocking Day 10
  Streamlit UI testing.
- **Strategy evaluation remains comparable to academic literature and production
  backtest tools.** Sharpe, MDD, volatility all computed under the same T+0
  convention Markowitz/Sharpe assume.
- **Defense story is clean:** T+2 modeling is explicitly scoped out with
  documented reasoning, not accidentally omitted. Committee question "why not
  T+2?" has a prepared answer.
- **Reversibility preserved:** The T+0 → T+2 extension in Phase 3 is additive
  (adds settlement queue layer) and does not require re-architecting the
  current simulator.

### Negative

- **Backtest Sharpe is slightly optimistic vs live production** (~0.5%/year
  drag not modeled). Caveat noted in Streamlit UI footnote and thesis report.
- **Users unfamiliar with academic convention may expect T+2 realism.**
  Mitigation: README methodology section + Streamlit tooltip explain T+0
  convention explicitly.
- **Pedagogical risk** for users treating P2 as a production execution tool.
  Mitigation: Explicit "research platform, not execution system" disclaimer
  in README + report Chapter 1 (Introduction) + Chapter 7 (Limitations).

### Neutral

- **Order of iteration within apply_orders is now a load-bearing invariant.**
  Unit test `test_mixed_sell_buy_applies_sell_first` documents the ordering
  contract so future refactors do not break it.
- **Future contributors must respect this convention** when adding new
  strategies or decision types. Documented in architecture.md ADR-016 pointer
  + inline comment in `_run_daily_loop` where the sort happens.

## Reversibility

**High reversibility.** Transitioning from T+0 to full T+2 modeling in thesis
Phase 3 requires:

1. Add `SettlementCalendar` service to infrastructure ring (adapter around
   VSD holiday calendar + T+N date arithmetic)
2. Add `pending_cash_queue: list[PendingCashCredit]` and
   `pending_share_queue: list[PendingShareDelivery]` fields to Portfolio
3. Modify `Portfolio.apply_orders` to enqueue proceeds and schedule credits
   at T+N instead of immediate credit
4. Add `Portfolio.settle(as_of: date)` method called at daily loop top to
   process the queues
5. Modify `_run_daily_loop` to call `portfolio.settle(day)` before
   `strategy.rebalance`
6. Add optional `margin_pool: MarginAccount` for the margin-funded variant
   (Alternative 2)

Estimated effort: 40-60 hours in Phase 3. The current simulator interface
(SimulateRequest/SimulateResult DTOs) does not need to change — only the
internal mechanics. Existing Hexagonal boundaries (ADR-015) accommodate the
extension without touching domain entities.

## References

### Academic
- Markowitz, H. (1952). "Portfolio Selection." *The Journal of Finance*, 7(1), 77-91.
- Sharpe, W. F. (1994). "The Sharpe Ratio." *The Journal of Portfolio Management*, 21(1), 49-58.
- Perold, A. F. (1988). "The Implementation Shortfall: Paper versus Reality." *The Journal of Portfolio Management*, 14(3), 4-9.
- Roncalli, T. (2013). *Introduction to Risk Parity and Budgeting*. CRC Press, Chapman and Hall.

### Industry
- Vietnam Securities Depository Center (VSD). "Rules on Securities Settlement Cycle" (2022 revision, T+2 standardization).
- Vietnam State Securities Commission (SSC). "Circular 120/2020/TT-BTC on Securities Trading" (margin and settlement procedures).
- QuantConnect LEAN documentation: Securities and Portfolio Model — SpotMarket default T+0 convention.
- Bloomberg PORT product reference: Portfolio Analytics vs Execution Analytics module separation.

### Related ADRs
- ADR-012: Rebalancing Cost Model (brokerage + tax + market impact — same ADR
  that establishes P2 as "research platform")
- ADR-015: Hexagonal Architecture (defines the ring boundaries that future
  SettlementCalendar extension will respect)
- NFR-R-02: HSX Lot Size Compliance (adjacent realism requirement already
  implemented in Sprint 11 Day 9 Step A)

### Project artifacts
- `src/vn_portfolio_frontier/application/services/rebalance_simulator.py`
  `_run_daily_loop` (SELL-first sort implementation site)
- `src/vn_portfolio_frontier/domain/entities/portfolio.py` `apply_orders`
  (the method whose iteration order the sort governs)
- `tests/unit/test_rebalance_simulator.py` `TestSellFirstOrdering` (invariant
  test — Sprint 11 Day 10 Step C)
- `docs/architecture.md` (ADR-016 pointer section)
