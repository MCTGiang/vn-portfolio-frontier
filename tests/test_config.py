"""Unit tests for Settings config loading.

Verifies:
- Settings can be instantiated with no env vars (all fields optional at default).
- get_settings() returns a cached singleton.
- Env var loading works with cache-clear pattern.
- SecretStr wrapping prevents accidental logging of the URL.
"""

from __future__ import annotations

import pytest

from vn_portfolio_frontier.config import Settings, get_settings


def test_settings_load_returns_settings_instance() -> None:
    """Bare load returns a Settings instance regardless of env state."""
    s = Settings()
    assert isinstance(s, Settings)


def test_get_settings_returns_cached_singleton() -> None:
    """Two calls return the same instance thanks to lru_cache."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_reads_neon_url_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When env has NEON_DATABASE_URL, Settings picks it up on fresh load."""
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://test@localhost/db")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.neon_database_url is not None
        assert s.neon_database_url.get_secret_value() == "postgresql://test@localhost/db"
    finally:
        get_settings.cache_clear()


def test_secretstr_hides_url_in_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SecretStr wrapping prevents URL leak in repr() or logs."""
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://secretuser@host/db")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.neon_database_url is not None
        assert "secretuser" not in repr(s.neon_database_url)
        assert "secretuser" not in repr(s)
    finally:
        get_settings.cache_clear()
