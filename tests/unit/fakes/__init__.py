"""Fake implementations of application.ports Protocols cho unit tests.

Dict-backed in-memory implementations satisfying Repository Protocol
contracts. Verified via isinstance checks trong test_ports.py.

Public exports:
    - FakePriceRepository
    - FakeRebalanceRunRepository
    - FakeRebalanceDecisionRepository
"""

from tests.unit.fakes.in_memory_repos import (
    FakePriceRepository,
    FakeRebalanceDecisionRepository,
    FakeRebalanceRunRepository,
)

__all__ = [
    "FakePriceRepository",
    "FakeRebalanceDecisionRepository",
    "FakeRebalanceRunRepository",
]
