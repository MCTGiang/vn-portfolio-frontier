"""RebalanceRunRepository Port + supporting DTOs.

Per ADR-015 §2.4 Repository Pattern. Application layer (RebalanceSimulator,
Day 6) depends on this Protocol; infrastructure (NeonRebalanceRunRepository)
implements it.

Shape maps to Migration 005 + 009 simulation.rebalance_run columns:
    - Input fields: brokerage_pct, tax_pct, market_impact_bps, strategy_name,
      strategy_params (JSONB), target_weights (JSONB), backtest_start/end
    - Reproducibility: git_commit_sha, code_version
    - Output (set after backtest): sharpe_before/after_cost, total_cost_bps,
      turnover_avg_pct, n_rebalances
    - Status (Migration 009): status, error_message

Design decisions:
    - **RunRecord** là frozen DTO: input + output fields together. Outputs
      Optional (None lúc chạy). Caller dùng `dataclasses.replace` để fill
      sau khi backtest xong. 1 save() = 1 INSERT (no UPDATE needed), match
      ADR-012 "every row = one scenario" semantics.
    - **RunSummary** separate DTO cho list_recent(): nhẹ hơn RunRecord
      (chỉ fields cần cho history UI table). Avoid pulling full
      strategy_params + target_weights JSONB khi chỉ list 20 recent runs.
    - **save() returns int** (not UUID): Migration 005 uses BIGSERIAL run_id
      (not UUID). PK generation stays DB-side.
    - **git_commit_sha + code_version** required fields: NFR-R-07
      reproducibility story — committee hỏi "làm sao biết run này từ code
      nào" → answer rõ qua git_commit_sha column.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

# =====================================================================
# DTOs
# =====================================================================


@dataclass(frozen=True)
class RunRecord:
    """Snapshot cho simulation.rebalance_run row.

    Input fields are required at construction. Output fields default None
    (unknown lúc INSERT initial). Use `dataclasses.replace(record, **outputs)`
    to produce the final record after backtest completes.

    Parameters
    ----------
    brokerage_pct : Decimal
        ADR-012 user-input broker commission rate.
    tax_pct : Decimal
        Vietnam seller tax (0.001 = 0.1% default per Thông tư 111/2013/TT-BTC).
    market_impact_bps : int
        Market-impact assumption in basis points.
    strategy_name : str
        Must match CHECK constraint ('periodic' | 'threshold_band' | 'hybrid').
    strategy_params : dict[str, Any]
        Strategy-specific params (JSONB). Example: {"band_bps": 500}.
    target_weights : dict[str, float]
        Target portfolio weights (JSONB). Example: {"VCB": 0.5, "FPT": 0.5}.
    backtest_start : date
        Start of backtest period (inclusive).
    backtest_end : date
        End of backtest period (inclusive). Must >= backtest_start.
    git_commit_sha : str
        40-char Git SHA for reproducibility.
    code_version : str
        Short semver / tag label (e.g. "v2.0-sprint11").
    initial_capital : Decimal
        Starting capital for backtest (VNĐ).
    sharpe_before_cost : Decimal | None, default None
        Sharpe ratio of gross returns (no cost drag).
    sharpe_after_cost : Decimal | None, default None
        Sharpe ratio of net returns (after brokerage + slippage + tax).
    total_cost_bps : int | None, default None
        Total cost as basis points of initial capital.
    turnover_avg_pct : Decimal | None, default None
        Average turnover per rebalance (%).
    n_rebalances : int | None, default None
        Count of actionable decisions (excluding no_action).
    status : str, default "completed"
        One of 'running' | 'completed' | 'failed' | 'cancelled'.
    error_message : str | None, default None
        Set when status='failed'.

    Raises
    ------
    ValueError
        If backtest_end < backtest_start, or git_commit_sha length != 40.
    """

    # Required: input
    brokerage_pct: Decimal
    tax_pct: Decimal
    market_impact_bps: int
    strategy_name: str
    strategy_params: dict[str, Any]
    target_weights: dict[str, float]
    backtest_start: date
    backtest_end: date
    git_commit_sha: str
    code_version: str
    initial_capital: Decimal

    # Optional: output (fill after backtest)
    sharpe_before_cost: Decimal | None = None
    sharpe_after_cost: Decimal | None = None
    total_cost_bps: int | None = None
    turnover_avg_pct: Decimal | None = None
    n_rebalances: int | None = None

    # Status
    status: str = "completed"
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.backtest_end < self.backtest_start:
            raise ValueError(
                f"RunRecord.backtest_end ({self.backtest_end}) must be >= "
                f"backtest_start ({self.backtest_start})"
            )
        if len(self.git_commit_sha) != 40:
            raise ValueError(
                f"RunRecord.git_commit_sha must be 40 chars (full SHA), "
                f"got {len(self.git_commit_sha)}"
            )
        if self.status not in ("running", "completed", "failed", "cancelled"):
            raise ValueError(
                f"RunRecord.status must be one of 'running'|'completed'|"
                f"'failed'|'cancelled', got {self.status!r}"
            )
        if self.initial_capital <= Decimal("0"):
            raise ValueError(
                f"RunRecord: initial_capital must be positive, got " f"{self.initial_capital}"
            )


@dataclass(frozen=True)
class RunSummary:
    """Lightweight DTO cho list_recent() history query.

    Carries only fields needed by Streamlit history table + "resume last run"
    workflow. Full strategy_params + target_weights deferred until user
    clicks a specific row (then find_by_id loads RunRecord).

    Parameters
    ----------
    run_id : int
        BIGSERIAL from simulation.rebalance_run.
    run_timestamp : datetime
        INSERT time (DEFAULT NOW()).
    strategy_name : str
        For display + filter.
    sharpe_after_cost : Decimal | None
        KPI shown in list (None nếu run chưa complete).
    status : str
        For badge color (running = yellow, completed = green, failed = red).
    """

    run_id: int
    run_timestamp: datetime
    strategy_name: str
    sharpe_after_cost: Decimal | None
    status: str


# =====================================================================
# Protocol
# =====================================================================


@runtime_checkable
class RebalanceRunRepository(Protocol):
    """Port cho simulation.rebalance_run access.

    Concrete implementations:
        - NeonRebalanceRunRepository (infrastructure, Sprint 11 Day 7)
        - FakeRebalanceRunRepository (tests/unit/fakes/, Day 4)
    """

    def save(self, record: RunRecord) -> int:
        """INSERT a run record and return the assigned run_id.

        Parameters
        ----------
        record : RunRecord
            Complete record (input + output fields). Status should be set.

        Returns
        -------
        int
            BIGSERIAL run_id assigned by DB. Caller uses this to persist
            associated RebalanceDecision rows (which have FK → run_id).

        Raises
        ------
        ValueError
            If record violates DB CHECK constraints (strategy_name unknown,
            brokerage_pct out of range, etc.) — caller sees DB error wrapped
            as ValueError.
        """
        ...

    def find_by_id(self, run_id: int) -> RunRecord | None:
        """Return the full RunRecord cho `run_id`, or None if not found.

        Parameters
        ----------
        run_id : int
            BIGSERIAL from a prior save() call.

        Returns
        -------
        RunRecord | None
            None (not an exception) when `run_id` doesn't exist. Callers
            should handle this explicitly.
        """
        ...

    def list_recent(self, limit: int = 20) -> list[RunSummary]:
        """Return the `limit` most-recent runs by run_timestamp DESC.

        Parameters
        ----------
        limit : int, default 20
            Max rows to return. Must be positive.

        Returns
        -------
        list[RunSummary]
            Chronologically descending (newest first). Empty list if no runs.

        Raises
        ------
        ValueError
            If limit <= 0.
        """
        ...
