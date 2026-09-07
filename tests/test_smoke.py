"""Smoke tests — verify package infrastructure is wired correctly.

These tests give CI something to run before feature code lands. All are
tagged 'unit' and complete in milliseconds. Once real modules exist, this
file can shrink or be replaced.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_package_importable() -> None:
    """The vn_portfolio_frontier package imports cleanly."""
    import vn_portfolio_frontier  # noqa: F401


@pytest.mark.unit
def test_version_is_nonempty_string() -> None:
    """Package exposes a __version__ string."""
    import vn_portfolio_frontier

    assert isinstance(vn_portfolio_frontier.__version__, str)
    assert len(vn_portfolio_frontier.__version__) >= 3


@pytest.mark.unit
def test_sample_tickers_fixture_yields_list(sample_tickers: list[str]) -> None:
    """conftest.sample_tickers fixture returns a non-empty ticker list."""
    assert isinstance(sample_tickers, list)
    assert len(sample_tickers) > 0
    assert all(isinstance(t, str) for t in sample_tickers)
