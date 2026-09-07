"""Shared pytest fixtures for vn-portfolio-frontier.

Following Project 1 lesson (ScopeMismatch): read-only fixtures — constants,
tickers, date windows — must be session-scoped so higher-scope consumers can
depend on them without pytest raising ScopeMismatch.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sample_tickers() -> list[str]:
    """Small sample of VN30 tickers for smoke tests.

    The full 29-ticker VN30 universe will be sourced from the Neon schema
    once Phase 2 (schema design) lands. This placeholder exists so early
    tests can exercise fixture wiring without depending on external data.
    """
    return ["VCB", "FPT", "HPG"]


@pytest.fixture(scope="session")
def data_window() -> tuple[date, date]:
    """Default data window inherited from Project 1's 5.6-year benchmark."""
    return date(2021, 1, 1), date(2026, 8, 20)


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Repository root — one level up from the tests/ directory."""
    return Path(__file__).parent.parent
