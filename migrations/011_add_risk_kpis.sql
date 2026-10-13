-- Migration 011: Add risk KPIs (Max Drawdown + Annualized Volatility)
--
-- Rationale (Day 8 Interpretability Layer):
--   Day 6-7 persisted 5 KPIs: n_rebalances, total_cost_bps,
--   turnover_avg_pct, sharpe_before_cost, sharpe_after_cost.
--   This is risk-management-incomplete: Sharpe alone does not convey
--   drawdown depth nor realized volatility. ADR-012 risk framework
--   requires MDD + annualized vol as first-class KPIs.
--
--   Enduser needs these to interpret portfolio behavior:
--   - Sharpe 0.66 is not actionable; "MDD -35% + Vol 22%/yr" is.
--
-- Idempotency: ADD COLUMN IF NOT EXISTS (Postgres 9.6+).
-- Backwards compatibility: columns are NULLable; historical runs keep
-- NULL (UI renders as "N/A" or "-").
--
-- Related: ADR-012 risk KPI section, Day 8 Interpretability Layer plan.

BEGIN;

ALTER TABLE simulation.rebalance_run
    ADD COLUMN IF NOT EXISTS max_drawdown_pct DECIMAL(8, 4),
    ADD COLUMN IF NOT EXISTS volatility_annualized_pct DECIMAL(8, 4);

COMMENT ON COLUMN simulation.rebalance_run.max_drawdown_pct IS
    'Maximum peak-to-trough drawdown over backtest, as a non-negative '
    'percentage (e.g. 35.0000 = -35% from peak). NULL if backtest '
    'failed before compute. Formula: max((peak - trough) / peak * 100) '
    'over daily_values_after_cost series.';

COMMENT ON COLUMN simulation.rebalance_run.volatility_annualized_pct IS
    'Annualized standard deviation of daily log returns, as a percentage '
    '(e.g. 22.5000 = 22.5%/year). Uses sqrt(252) trading-day scaling. '
    'NULL if backtest failed or <2 trading days.';

COMMIT;
