"""RebalanceDecisionRepository Port - simulation.rebalance_decision access.

Per ADR-015 section 2.4 Repository Pattern. Decisions link to a Run via run_id FK;
one Run can have 0-N Decisions (0 = all days were no-action within band).

Serialization notes (Infrastructure impl responsibility, not Port):
    - RebalanceDecision.orders: tuple[Order, ...] -> JSONB array per decision
      Example: [{"ticker":"VCB","side":"BUY","shares":100,"est_price":125000}, ...]
    - RebalanceDecision.costs: TradingCost -> flatten to 3 cost_* columns
      (cost_brokerage + cost_slippage + cost_tax + cost_total derived)
    - RebalanceDecision.weights_before/after: dict[str, float] -> JSONB
    - Order.est_price Decimal -> NUMERIC(20,2) with HALF_UP quantize

Design:
    - Only 2 methods: save_batch + find_by_run - Sprint 11 scope doesn't
      need find_by_id (per-decision lookup) or delete (CASCADE from parent)
    - save_batch requires run_id to exist first (FK) - caller flow must
      RebalanceRunRepository.save() -> get run_id -> save_batch(run_id, ...)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from vn_portfolio_frontier.domain.entities.rebalance_decision import RebalanceDecision


@runtime_checkable
class RebalanceDecisionRepository(Protocol):
    """Port cho simulation.rebalance_decision access.

    Concrete implementations:
        - NeonRebalanceDecisionRepository (infrastructure, Sprint 11 Day 7)
        - FakeRebalanceDecisionRepository (tests/unit/fakes/, Day 4)
    """

    def save_batch(
        self,
        run_id: int,
        decisions: Sequence[RebalanceDecision],
    ) -> int:
        """INSERT a batch of decisions linked to `run_id`.

        Parameters
        ----------
        run_id : int
            Parent run's BIGSERIAL id. Must exist in simulation.rebalance_run
            (FK constraint, DB enforced). Caller flow: save the RunRecord
            first, then save its decisions in a single batch call.
        decisions : Sequence[RebalanceDecision]
            Decisions to persist. Empty sequence is a no-op (returns 0).
            Decisions are inserted in the given sequence order; `decision_id`
            BIGSERIAL assigned by DB preserves order within a run.

        Returns
        -------
        int
            Count of rows inserted. Equals `len(decisions)` on happy path.
            Returns 0 for empty input (not an error - all-no-action runs are
            common when band is wide).

        Raises
        ------
        ValueError
            If run_id doesn't exist (FK violation surfaces as DB error wrapped
            to ValueError at Infrastructure layer).

        Notes
        -----
        - NOT idempotent cross-batch: calling save_batch twice with same
          decisions inserts duplicates (no PK conflict since decision_id is
          BIGSERIAL). Caller responsibility: don't call twice per run.
        - Transactional per-batch: all N decisions commit together, or none
          (per Postgres transaction default). Partial-apply impossible.
        """
        ...

    def find_by_run(self, run_id: int) -> list[RebalanceDecision]:
        """Return all decisions for one run, ordered by trigger_date ASC.

        Parameters
        ----------
        run_id : int
            Parent run's BIGSERIAL id.

        Returns
        -------
        list[RebalanceDecision]
            Decisions chronologically ordered. Empty list if run_id has no
            decisions (all-no-action case) OR if run_id doesn't exist (same
            empty return - caller must verify run existence via
            RebalanceRunRepository.find_by_id if distinction matters).

        Notes
        -----
        - Each returned RebalanceDecision reconstructs orders tuple +
          TradingCost + weights dicts from JSONB columns + cost_* columns
        - decision_id BIGSERIAL is NOT exposed in RebalanceDecision (domain
          entity has no identity field) - Repository drops it after fetch
        """
        ...
