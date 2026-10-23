# ADR-017: FrontierOptimizer via scipy.optimize (not vnstock_quant)

**Status:** Accepted — 2026-10-20

## Context

Day 11 Sprint 11 built F1 Efficient Frontier feature (Markowitz 1952 portfolio theory): 3 reference portfolios (MinVar/MaxSharpe/RiskParity) + N-point frontier curve + end-user slider UI. Original plan (locked 14/10 per Sprint 11 Day 9+ preamble) was to use `vnstock_quant.portfolio` module as the solver — it provides built-in Min Variance, Max Sharpe, Risk Parity, Rust-core performance (~25x faster than scipy), and TA-Lib/LEAN cross-validated accuracy. Expected savings: ~15-20h implementation vs self-implementing CVXPY/scipy from scratch.

During Day 11 implementation (20-21/10), two critical issues surfaced:

1. **`vnstock_quant.portfolio` requires valid vnstock auth internally**. Calling optimization functions triggers `vnstock.auth.verify_credential()` which checks the Sponsor Silver API key with vnstocks.com backend. If the key is invalid/revoked/network-blocked, the whole module raises `VNSTOCK_AUTH_CREDENTIAL_INVALID`.

2. **VNSTOCK API key authentication stuck for 4+ days** (both old and new rotated keys returned `INVALID_CREDENTIAL` despite the dashboard showing Silver tier active with 99-100% quota remaining). Support ticket opened with vnstocks.com in parallel but no ETA for resolution.

The coupling between `vnstock_quant.portfolio` (pure mathematical optimization, no network-sensitive data) and `vnstock.auth` (networked credential verification) violates ADR-015 Hexagonal boundaries: the domain ring should contain pure math with zero vendor SDK state dependency.

## Decision

**Implement FrontierOptimizer internally using `scipy.optimize.minimize` with SLSQP (Sequential Least Squares Programming) method**, replacing the planned vnstock_quant dependency. The public API of FrontierOptimizer (`compute_frontier(mu, cov, points, bounds, rf_daily) -> FrontierCurve`) stays identical to what would have been exposed via vnstock_quant wrapper, so no cascading changes to FrontierService or Streamlit UI.

Key implementation details:
- 4 helper functions: `_scipy_min_variance`, `_scipy_max_sharpe`, `_scipy_risk_parity`, `_scipy_frontier`
- Constraint: weights sum to 1.0 (budget), per-asset bounds via `WeightBounds(lower, upper)`
- SLSQP method chosen for inequality constraint support + convergence on QP problems
- `rf_daily` parameter for Sharpe calculation (zero default per Perold 1988 convention)

## Alternatives considered

1. **Wait for VNSTOCK auth fix** — Blocked Sprint 11 timeline (defense 17/11), no ETA.
2. **CVXPY** — Heavier install (~500MB), overkill for N=6-30 assets, slower than scipy for this problem size.
3. **PyPortfolioOpt library** — External dep with its own install footprint and auth-free, but adds a 3rd-party coupling just to delegate what scipy does in 20 lines.
4. **Self-implement Lagrangian solver** — Rejected (reinvent wheel, longer defense story to justify).

## Consequences

**Positive:**
- Domain layer stays pure per ADR-015 Hex boundaries — zero vendor SDK dependency, zero network calls in optimization math.
- Deterministic + reproducible: same inputs → same outputs across runs.
- Mock-friendly for unit tests: 42 tests shipped (20 FrontierOptimizer + 22 FrontierService), coverage 86% + 100%.
- Industry-standard choice: scipy.optimize is default in LEAN, zipline, backtrader academic/professional stacks.
- Defense story clean: "Markowitz 1952 (Nobel 1990 for Markowitz, Sharpe, Miller) + scipy.optimize SLSQP (industry-standard QP solver)".
- No install footprint change: scipy already required by vn-portfolio-frontier's existing dependencies.

**Negative:**
- Slower than vnstock_quant Rust-core (~ms per call at N=6-30, acceptable for Streamlit interactive use).
- 15-20h actual implementation vs the "0h use pre-built" plan — but net faster than waiting on VNSTOCK auth fix.
- Future refactor option: when VNSTOCK auth stabilizes, could add vnstock_quant as alternative solver via Strategy pattern. Deferred until auth proven stable for 1+ month.

**Neutral:**
- VNSTOCK Sponsor Silver subscription cost unchanged (still needed for `vnstock.Quote`, `vnstock.Fundamental`, `vnstock.Macro`, `vnstock.Reference` data access across Project 2).

## References

- Markowitz, H. (1952). "Portfolio Selection". *Journal of Finance* 7(1): 77-91.
- Roncalli, T. (2013). *Introduction to Risk Parity and Budgeting*. Chapman and Hall.
- scipy.optimize SLSQP: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html
- Related ADRs: [ADR-015 Hexagonal Architecture](./adr-015-hexagonal.md)
- Related code: `src/vn_portfolio_frontier/domain/services/frontier_optimizer.py` + tests `tests/unit/test_frontier_optimizer.py`
- Day 11 PR: #43 commit 9cf305c
